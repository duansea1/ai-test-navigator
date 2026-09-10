"""项目管理域：工作区项目扫描、git 快照。"""
from __future__ import annotations

import subprocess
from pathlib import Path

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
def list_projects(workspace: str = "") -> dict[str, object]:
    """列出工作区下的项目目录。前端可传 ?workspace= 切换目录（纯前端改目录、免改配置）。
    传入的目录若不存在则回退后端默认 s.workspace；workspace_matched=False 表示发生了回退，
    前端据此提示「目录不存在」。"""
    s = get_settings()
    requested = workspace.strip()
    root = Path(requested).resolve() if requested else s.workspace
    if not root.exists() or not root.is_dir():
        root = s.workspace
    matched = (not requested) or (Path(requested).resolve() == root)
    items = []
    if root.exists():
        for entry in sorted(root.iterdir()):
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
    return {"requested_workspace": requested, "workspace": str(root),
            "workspace_matched": matched, "default_branch": s.branch, "projects": items}
