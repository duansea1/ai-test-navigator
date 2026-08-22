"""项目管理域：工作区项目扫描、git 快照。"""
from __future__ import annotations

import subprocess
from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["projects"])


def _git_branch(project_dir) -> str:
    try:
        result = subprocess.run(["git", "-C", str(project_dir), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() or "-"
    except (OSError, subprocess.SubprocessError):
        return "-"


def _git_commit(project_dir) -> str:
    try:
        result = subprocess.run(["git", "-C", str(project_dir), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() or "-"
    except (OSError, subprocess.SubprocessError):
        return "-"


@router.get("/projects")
def list_projects() -> dict[str, object]:
    s = get_settings()
    items = []
    if s.workspace.exists():
        for entry in sorted(s.workspace.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            has_git = (entry / ".git").exists()
            items.append(
                {
                    "name": entry.name,
                    "is_git": has_git,
                    "branch": _git_branch(entry) if has_git else "",
                    "commit": _git_commit(entry) if has_git else "",
                }
            )
    return {"workspace": str(s.workspace), "default_branch": s.branch, "projects": items}
