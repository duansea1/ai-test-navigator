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

from app.dsh import agents as agent_registry
from app.dsh.runtime import manager as dsh_manager

# 兜底启发式（仅当 DSH 真不可用时；极简，避免与模型规则双头维护）
_FULL_KEYWORDS = ("生成报告", "出报告", "全流程", "完整分析", "跑一遍", "跑全流程")
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
    """模型优先：失败原地重试一次再兜底（铁律「尽可能调起 AI」——瞬时故障不轻易降级）。"""
    res = _try_turn(prompt, session_id)
    if res.get("status") == "ok":
        return res
    return _try_turn(prompt, session_id)


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


def _router_session(conversation_id: str | None) -> str:
    """每个会话一条常驻 DSH 路由会话：同 conversation_id 的回合共享上下文。"""
    return f"conv-{conversation_id}--router" if conversation_id else "router-global"


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


def classify(text: str, conversation_id: str | None = None) -> dict:
    """意图识别：一律先调 DSH intent-classifier（规则在 prompt/skill 里，模型说了算）；
    仅 DSH 真不可用时启发式兜底，兜底不覆盖模型结果。reason 始终随行——
    模型给的 reason 是「为什么这么分」，兜底的 reason 标注启发式，前端可见。

    多轮会话：同一 conversation 复用 DSH 会话 + 注入历史摘要，
    追问（「那帮我分析下它」）能被放进正确的语境里分类。"""
    t = (text or "").strip()
    prompt = _agent_prompt("intent-classifier")
    history = _history_block(conversation_id)
    res = _dsh_turn(f"{prompt}\n\n{history}用户输入：{t}",
                    _router_session(conversation_id)) if prompt else {"status": "error"}
    if res.get("status") == "ok":
        data = _extract_intent(res.get("final_response", ""))
        if data:
            return data
    # 兜底启发式（仅当 DSH 不可用；模型可用时永不走到这里）
    if t.endswith(("？", "?", "吗")) or len(_strip_punct(t)) <= 6:
        return {"intent": "qa", "confidence": 0.6, "reason": "启发式（DSH 不可用）：疑似问答"}
    if any(k in t for k in _FULL_KEYWORDS):
        return {"intent": "full", "confidence": 0.6, "reason": "启发式（DSH 不可用）：疑似全流程"}
    return {"intent": "analyze", "confidence": 0.6, "reason": "启发式（DSH 不可用）：默认需求分析"}


def qa_answer(text: str, conversation_id: str | None = None) -> str:
    """问答式回答：一律先调 DSH qa-assistant（问候也不例外）；
    不可用时明说「未调用 AI」并给能力引导。

    多轮会话：同一 conversation 复用 DSH 会话（模型自带记忆），
    另注入历史摘要兜底（DSH 会话被清理/重启后仍能接上话）。"""
    t = (text or "").strip()
    prompt = _agent_prompt("qa-assistant")
    history = _history_block(conversation_id)
    res = _dsh_turn(f"{prompt}\n\n{history}用户：{t}",
                    _router_session(conversation_id)) if prompt else {"status": "error"}
    if res.get("status") == "ok":
        return (res.get("final_response") or "").strip() or "（模型未返回内容）"
    return _OFFLINE_REPLY
