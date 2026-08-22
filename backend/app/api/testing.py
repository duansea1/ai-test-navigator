"""测试中心域：M3 落地测试执行引擎（白名单命令、日志、归因）。"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["testing"])


@router.get("/testing")
def testing_overview() -> dict[str, object]:
    return {
        "status": "planned",
        "milestone": "M3",
        "planned": ["Maven/Gradle 单元测试", "pytest", "npm lint/build/test", "API 测试", "数据库校验", "失败归因"],
        "message": "测试执行引擎将在 M3 落地：白名单命令 + dry-run 先行。",
    }
