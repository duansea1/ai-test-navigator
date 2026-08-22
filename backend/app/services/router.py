"""意图路由：用 DSH 做智能意图识别与问答，区分 问答 / 需求分析 / 全流程。

最高约束：一律走 DSH 语义识别（最优解）；仅当 DSH 不可用时才回退启发式，
绝不把单一全流程硬套所有输入。
"""
from __future__ import annotations

import json
import re

from app.dsh.runtime import manager as dsh_manager

_INTENT_PROMPT = (
    "你是意图分类器。判断用户输入属于哪一类，只输出 JSON："
    "{\"intent\":\"qa|analyze|full\",\"confidence\":0.0,\"reason\":\"简短理由\"}。"
    "qa=问答/闲聊/询问工具能力（如『你有什么能力』『怎么用』）；"
    "analyze=需求分析但不要求出报告（如『分析下这个需求』『这个改动影响哪些接口』）；"
    "full=明确要求完整分析并生成报告（如『分析并生成报告』『跑全流程』）。"
    "只输出 JSON，不要任何解释。"
)
_QA_PROMPT = (
    "你是「AI 测试导航」助手，回答用户关于本工具、测试方法论、代码分析能力的问题，"
    "简洁、专业、用中文。若用户问的是具体代码需求，引导其切换到「需求分析/全流程」模式。"
)

_QA_KEYWORDS = ("你有什么能力", "你会", "怎么用", "是什么", "什么是", "为什么", "如何", "能不能", "可以吗", "介绍下", "帮我理解")
_FULL_KEYWORDS = ("生成报告", "出报告", "全流程", "完整分析", "跑一遍", "跑全流程")


def _dsh_turn(prompt: str, session_id: str) -> dict:
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


def classify(text: str) -> dict:
    """意图识别：DSH 优先，失败回退启发式。"""
    t = (text or "").strip()
    res = _dsh_turn(f"{_INTENT_PROMPT}\n\n用户输入：{t}", "router-intent")
    if res.get("status") == "ok":
        data = _extract_intent(res.get("final_response", ""))
        if data:
            return data
    # 回退启发式（仅当 DSH 不可用）
    if t.endswith(("？", "?", "吗")) or any(k in t for k in _QA_KEYWORDS):
        return {"intent": "qa", "confidence": 0.6, "reason": "启发式：疑似问答"}
    if any(k in t for k in _FULL_KEYWORDS):
        return {"intent": "full", "confidence": 0.6, "reason": "启发式：疑似全流程"}
    return {"intent": "analyze", "confidence": 0.6, "reason": "启发式：默认需求分析"}


def qa_answer(text: str) -> str:
    """问答式回答：DSH 对话，失败回退说明。"""
    t = (text or "").strip()
    res = _dsh_turn(f"{_QA_PROMPT}\n\n用户：{t}", "router-qa")
    if res.get("status") == "ok":
        return (res.get("final_response") or "").strip() or "（模型未返回内容）"
    return "当前 DSH 未就绪，无法实时回答。请配置模型 Key 后重试，或切换到「需求分析/全流程」模式。"
