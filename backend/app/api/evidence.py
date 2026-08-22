"""证据中心域：M1/M2 落地代码证据检索与 PROJECT_INDEX 知识库。"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["evidence"])


@router.get("/evidence")
def evidence_overview() -> dict[str, object]:
    return {
        "status": "planned",
        "milestone": "M1/M2",
        "planned": ["代码证据检索", "调用链浏览", "PROJECT_INDEX 知识检索", "证据引用跳转"],
    }
