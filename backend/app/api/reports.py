"""报告中心域：报告列表与文件服务（迁移 MVP 的 /reports 端点）。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import get_settings

router = APIRouter(tags=["reports"])
file_router = APIRouter()


@router.get("/reports")
def list_reports() -> dict[str, object]:
    s = get_settings()
    items = []
    for path in sorted(s.report_dir.glob("RPT-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            summary = data.get("summary", {})
            items.append(
                {
                    "report_id": data.get("report_id", path.stem),
                    "generated_at": data.get("generated_at", ""),
                    "branch": data.get("branch", ""),
                    "projects": data.get("projects", []),
                    "summary": summary,
                    "files": {
                        "json": f"/reports/{path.name}",
                        "markdown": f"/reports/{path.stem}.md",
                        "html": f"/reports/{path.stem}.html",
                    },
                }
            )
        except (OSError, ValueError):
            continue
    return {"reports": items}


@file_router.get("/reports/{filename}")
def report_file(filename: str) -> FileResponse:
    s = get_settings()
    path = (s.report_dir / filename).resolve()
    if path.parent != s.report_dir.resolve() or not path.exists():
        raise HTTPException(status_code=404, detail=f"报告 {filename} 不存在")
    return FileResponse(path)
