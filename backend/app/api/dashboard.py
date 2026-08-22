"""工作台域：任务总览、风险分布、趋势。

M1：DB（analysis_tasks/requirements）为主数据源，报告文件为辅（MVP 时期历史数据）。
DB 不可用时降级回报告文件统计，保证页面可用。
"""
from __future__ import annotations

import json

from fastapi import APIRouter

from app.core.config import get_settings
from app.db import entities
from app.dsh.runtime import manager

router = APIRouter(tags=["dashboard"])


def _stats_from_reports() -> dict[str, object]:
    """降级统计：扫报告文件（DB 不可用时）。"""
    s = get_settings()
    reports = []
    for path in sorted(s.report_dir.glob("RPT-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            reports.append({"report_id": data.get("report_id"), "generated_at": data.get("generated_at"), "summary": data.get("summary", {}), "branch": data.get("branch", "")})
        except (OSError, ValueError):
            continue
    totals = {
        "reports": len(reports),
        "requirements": sum(r["summary"].get("requirements", 0) for r in reports),
        "evidence": sum(r["summary"].get("evidence", 0) for r in reports),
        "test_cases": sum(r["summary"].get("test_cases", 0) for r in reports),
        "needs_review": sum(r["summary"].get("needs_review", 0) for r in reports),
    }
    return {"totals": totals, "recent_reports": reports[:10], "tasks": [], "trend": [], "source": "files"}


@router.get("/dashboard")
def dashboard() -> dict[str, object]:
    try:
        stats = entities.dashboard_stats()
        tasks = entities.list_tasks(limit=10)
        trend = entities.dashboard_trend(14)
        return {
            "totals": {
                "reports": stats["tasks_completed"],
                "requirements": stats["requirements_total"],
                "evidence": stats["evidence_total"],
                "test_cases": stats["test_cases_total"],
                "needs_review": stats["needs_review_total"],
                "tasks_total": stats["tasks_total"],
                "tasks_running": stats["tasks_running"],
                "tasks_failed": stats["tasks_failed"],
            },
            "tasks": tasks,
            "trend": trend,
            "recent_reports": [],
            "dsh": manager.availability(),
            "source": "db",
        }
    except Exception:
        # DB 不可用：降级报告文件统计（MVP 行为），页面不空白
        data = _stats_from_reports()
        data["dsh"] = manager.availability()
        return data
