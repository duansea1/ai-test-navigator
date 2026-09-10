"""意图路由 + 多轮会话服务：用 DSH 做智能意图识别与问答，区分 问答 / 需求分析 / 全流程。

架构定位（2026-08-25 用户定调）：平台的智能长在 Agent 角色的 skills/rules 里，
不长在代码里。本模块只做三件事：
  1. 把输入递给模型（prompt 来自 agents.py 注册表，规则写在 system_prompt
     与 skills/routing-rules——问候/闲聊/混合句怎么分，是模型读的规则，不是 if 关键字）；
  2. 多轮会话（2026-08-26）：每个 conversation 一条独立 DSH 会话（conv-xxx--router），
     模型自带跨回合记忆；追问里「刚才那个需求」这类指代由模型在会话内消解，
     平台只注入轻量上下文（历史问答摘要 + 最近任务结论），不自己拼历史消息。
  3. 模型真不可用时的显式降级（reason 标注启发式，永不覆盖模型结果）。
代码里不再维护问候词表/关键词清单。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from app.dsh import agents as agent_registry
from app.dsh.runtime import manager as dsh_manager

# 兜底启发式（仅当 DSH 真不可用时；极简，避免与模型规则双头维护）
_FULL_KEYWORDS = ("生成报告", "出报告", "全流程", "完整分析", "跑一遍", "跑全流程")
# 问句特征（启发式兜底专用）：问号可在句中（「…结论如何？一句话概括」），
# 常见疑问词也视为问句倾向——与 intent-classifier prompt 的「拿不准倾向 qa」对齐
_QA_HINTS = ("？", "?", "如何", "怎么", "怎样", "什么", "为什么", "哪些", "多少", "吗", "呢")
# DSH 不可用时的问答回退：明说没调 AI，不假装回答
_OFFLINE_REPLY = (
    "当前 DSH Runtime 未就绪，本次回答未调用 AI 模型。\n\n"
    "我是「AI 测试导航」：把需求描述、接口 URL 或需求文档发给我，"
    "8 个 FDE Agent 会协同完成需求结构化 → 代码证据定位 → 调用链影响 → 实现审查 → "
    "测试设计 → 质量裁决 → 三视角报告。\n"
    "配置模型 Key（~/.dsh/.credentials.yaml 或 DEEPSEEK_API_KEY）后即可体验完整分析。"
)

# 单回合注入的历史消息条数上限（控制 token；DSH 会话本身还有 compaction）
_HISTORY_LIMIT = 12
# 每条历史消息的截断长度
_HISTORY_TRUNC = 400


def _strip_punct(t: str) -> str:
    """去空白与标点（兜底启发式用），小写化。"""
    return re.sub(r"[\s!！。.，,、~～?？…；;：:]", "", t.lower())


def _try_turn(prompt: str, session_id: str) -> dict:
    try:
        return dsh_manager.run_turn(prompt, session_id=session_id) or {}
    except Exception:  # noqa: BLE001
        return {"status": "error"}


def _dsh_turn(prompt: str, session_id: str) -> dict:
    """模型优先：失败退避重试一次再兜底（铁律「尽可能调起 AI」——瞬时故障不轻易降级）。

    2026-09-01：重试前加 1.5s 退避——实测任务流水线刚跑完时 node 载体可能
    短暂忙，原地立即重试同样失败；退避一次能把多数瞬时故障救回来。"""
    res = _try_turn(prompt, session_id)
    if res.get("status") == "ok":
        return res
    time.sleep(1.5)
    return _try_turn(prompt, session_id)


def _stream_turn(prompt: str, session_id: str,
                 on_delta: Callable[[str], None] | None = None) -> dict:
    """流式模型回合：on_delta 收到模型文本增量（DSH assistant/message 事件按条推送）。

    事件粒度是「一段 assistant 消息」而非逐 token——已是 DSH SDK 对外暴露的最细粒度，
    对问答打字机效果足够。on_delta 异常不阻断回合；不用时与 _dsh_turn 等价。"""
    def _handler(event: dict) -> None:
        if on_delta is None:
            return
        try:
            if str(event.get("type", "")) != "assistant/message":
                return
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            message = data.get("message") if isinstance(data.get("message"), dict) else data
            content = message.get("content")
            if isinstance(content, list):
                text = "".join(
                    str(b.get("text", "")) for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ).strip()
                if text:
                    on_delta(text)
        except Exception:  # noqa: BLE001 回调失败不影响回合
            pass

    try:
        res = dsh_manager.run_turn(prompt, session_id=session_id, on_event=_handler) or {}
    except Exception:  # noqa: BLE001
        res = {"status": "error"}
    if res.get("status") == "ok":
        return res
    # 瞬时失败退避重试一次（与 _dsh_turn 同策略；重试期间不再推流，避免重复）
    time.sleep(1.5)
    try:
        return dsh_manager.run_turn(prompt, session_id=session_id) or {}
    except Exception:  # noqa: BLE001
        return {"status": "error"}


def _extract_intent(text: str) -> dict | None:
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        d = json.loads(m.group(0))
        intent = str(d.get("intent", "")).lower()
        if intent in ("qa", "analyze", "full"):
            return {
                "intent": intent,
                "confidence": float(d.get("confidence", 0.8)),
                "reason": str(d.get("reason", "")),
            }
    except Exception:
        return None
    return None


def _agent_prompt(agent_id: str) -> str:
    """从注册表取 system_prompt（找不到时为空，由调用方兜底）。"""
    agent = agent_registry.get_agent(agent_id)
    return agent.system_prompt if agent else ""


def _router_session(conversation_id: str | None, role: str = "router") -> str:
    """每个会话 × 每个路由 Agent 一条独立 DSH 会话。

    2026-08-27 修复：classify（intent-classifier）与 qa_answer（qa-assistant）是
    **两个不同 Agent**，system_prompt 不同——若共用一条 DSH 会话，第一回合把会话
    定型成意图分类器（输出 JSON），第二回合塞 qa-assistant 的 prompt 进去会污染
    上下文，模型易续写 JSON 或只产思考链不产正文 → final_response 为空
    （「模型未返回内容」）。现在按 Agent 分会话，各自干净、各自保留多轮记忆。"""
    return f"conv-{conversation_id}--{role}" if conversation_id else f"router-global--{role}"


def _history_block(conversation_id: str | None) -> str:
    """本会话最近历史消息摘要（qa 问答 + 任务结论一句话），注入提示词。"""
    if not conversation_id:
        return ""
    try:
        from app.db import entities
        msgs = entities.list_messages(conversation_id, limit=_HISTORY_LIMIT)
    except Exception:  # DB 不可用时纯靠 DSH 会话记忆
        return ""
    if not msgs:
        return ""
    lines = []
    for m in msgs:
        role = "用户" if m.get("role") == "user" else "助手"
        content = str(m.get("content", "")).replace("\n", " ")[:_HISTORY_TRUNC]
        tag = f"[任务 {m.get('task_id')}]" if m.get("task_id") else ""
        lines.append(f"{role}{tag}：{content}")
    return "本会话最近的对话（新输入可能承接其中话题）：\n" + "\n".join(lines) + "\n\n"


def _project_block(projects: list[str] | None) -> str:
    """用户选中的目标项目（可能为空=自动侦察）。
    注入提示词，让模型知道用户基于哪个项目提问/分析——
    问答才能落到具体项目上，意图判断也能更贴合。"""
    if not projects:
        return ""
    names = "、".join(projects)
    return f"用户选定的目标项目：{names}（用户的提问/分析基于这些项目）\n\n"


def _workspace_block(workspace: str | None) -> str:
    """用户选定的源码工作区（绝对路径）注入提示词。

    问答链路同样必须带工作区：否则模型根本不知道源码在哪，只能凭记忆空答
    （2026-09-04 实测「问 AI 它不去查文件」的根因——/api/chat 与 qa_answer_result
    此前都不接收 workspace，prompt 里只有项目名、没有可检索的路径）。
    """
    w = (workspace or "").strip()
    if not w:
        return ""
    return (f"源码工作区：{w}\n"
            "涉及具体代码/接口/实现的问题，必须用 glob/grep/read 工具在该工作区内实际检索后"
            f"再回答；工具调用的 path 一律用绝对路径且以该工作区开头（例如 {w}\\<项目目录>\\src\\...），"
            "禁止相对路径。检索不到就明说未找到，不要凭记忆编造。\n\n")


def classify(text: str, conversation_id: str | None = None,
             projects: list[str] | None = None) -> dict:
    """意图识别：一律先调 DSH intent-classifier（规则在 prompt/skill 里，模型说了算）；
    仅 DSH 真不可用时启发式兜底，兜底不覆盖模型结果。reason 始终随行——
    模型给的 reason 是「为什么这么分」，兜底的 reason 标注启发式，前端可见。

    多轮会话：同一 conversation 复用 DSH 会话 + 注入历史摘要，
    追问（「那帮我分析下它」）能被放进正确的语境里分类。
    projects：用户选中的目标项目（可能为空=自动侦察）。
    选了项目时注入「目标项目」段，让模型知道用户基于哪个项目提问——
    不影响 qa/analyze/full 的判定，但 reason 能更贴合。"""
    t = (text or "").strip()
    prompt = _agent_prompt("intent-classifier")
    history = _history_block(conversation_id)
    proj_block = _project_block(projects)
    res = _dsh_turn(f"{prompt}\n\n{history}{proj_block}用户输入：{t}",
                    _router_session(conversation_id, "intent")) if prompt else {"status": "error"}
    if res.get("status") == "ok":
        data = _extract_intent(res.get("final_response", ""))
        if data:
            return data
    # 兜底启发式（模型真失败/输出未解析时；模型可用且解析成功时永不走到这里）。
    # 2026-09-01：reason 必须说真话——模型调用失败（404/配额/超时）、DSH 未就绪、
    # 输出未解析出意图 JSON 是三种不同的失败，此前统一标「DSH 不可用」误导排障。
    why = _failure_note(res, prompt)
    # 问句特征放宽到句中问号 + 疑问词（2026-09-01 实测：「…结论如何？一句话概括」
    # 问号在句中被 endswith 漏判成 analyze，追问被错建任务）。与分类 prompt 的
    # 「拿不准倾向 qa」对齐——宁可多聊一句，不要把追问错建分析任务。
    if any(h in t for h in _QA_HINTS) or len(_strip_punct(t)) <= 6:
        return {"intent": "qa", "confidence": 0.6, "reason": f"启发式兜底{why}：疑似问答"}
    if any(k in t for k in _FULL_KEYWORDS):
        return {"intent": "full", "confidence": 0.6, "reason": f"启发式兜底{why}：疑似全流程"}
    return {"intent": "analyze", "confidence": 0.6, "reason": f"启发式兜底{why}：默认需求分析"}


def _failure_note(res: dict, prompt: str) -> str:
    """分类失败的真因标注（启发式 reason 随行，前端与排障可见）。"""
    if not prompt:
        return "（intent-classifier 未注册）"
    status = res.get("status")
    if status == "error":
        return f"（模型调用失败：{str(res.get('message', ''))[:100]}）"
    if status == "fallback":
        return f"（DSH Runtime 未就绪：{str(res.get('message', ''))[:100]}）"
    return "（模型输出未解析出意图 JSON）"


def qa_answer_result(text: str, conversation_id: str | None = None,
                     projects: list[str] | None = None,
                     workspace: str | None = None,
                     on_delta: Callable[[str], None] | None = None) -> dict:
    """qa_answer 的结构化版本：{answer, model_error}。

    model_error 非空 = 模型被调了但失败（404/配额/超时等）——answer 是给用户看的
    明确提示（含真因与换模型指引），model_error 是给前端做错误样式/重试入口的信号。
    此前这一路径只回「（模型未返回内容）」，真因（如切了不存在的模型名）被吞掉，
    页面一片空白也没法重试（2026-09-01 修复）。"""
    t = (text or "").strip()
    prompt = _agent_prompt("qa-assistant")
    history = _history_block(conversation_id)
    ws_block = _workspace_block(workspace)
    proj_block = _project_block(projects)
    res = _stream_turn(f"{prompt}\n\n{history}{ws_block}{proj_block}用户：{t}",
                       _router_session(conversation_id, "qa"),
                       on_delta=on_delta) if prompt else {"status": "error"}
    if res.get("status") == "ok":
        return {"answer": (res.get("final_response") or "").strip() or "（模型未返回内容）",
                "model_error": None}
    if res.get("status") == "error":
        # 模型被调了但报错：说真因，指引用户换模型后重试（重试由前端提供入口）
        detail = str(res.get("message", ""))[:200]
        return {"answer": f"⚠️ 模型调用失败，本次回答未生成。\n\n原因：{detail}\n\n"
                          "可在左下角切换模型后点重试（或重新发送）。",
                "model_error": detail or "模型调用出错"}
    return {"answer": _OFFLINE_REPLY, "model_error": None}


def qa_answer(text: str, conversation_id: str | None = None,
              projects: list[str] | None = None,
              workspace: str | None = None,
              on_delta: Callable[[str], None] | None = None) -> str:
    """问答式回答：一律先调 DSH qa-assistant（问候也不例外）；
    不可用时明说「未调用 AI」并给能力引导；模型报错时说真因。

    多轮会话：同一 conversation 复用 DSH 会话（模型自带记忆），
    另注入历史摘要兜底（DSH 会话被清理/重启后仍能接上话）。
    projects：用户选中的目标项目——问答也要基于该项目回答。
    用户问「这个项目的登录怎么测」，不带项目就是无源之水；
    选了项目时注入项目名，让模型把回答落到具体项目上。
    on_delta：流式回调——DSH 每段 assistant 消息实时推给前端打字机显示。"""
    return qa_answer_result(text, conversation_id, projects, workspace, on_delta)["answer"]
