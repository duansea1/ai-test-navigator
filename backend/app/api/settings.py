"""系统设置域：健康检查、能力声明、DSH Runtime 状态。"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.dsh.runtime import manager

router = APIRouter(tags=["settings"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "commercial-fde", "version": "2.0.0"}


@router.get("/capabilities")
def capabilities() -> dict[str, object]:
    s = get_settings()
    return {
        "vision_supported": False,
        "dsh_key_configured": s.dsh_credential_configured,
        "dsh_ready": s.dsh_ready,
        "dsh_runtime": manager.availability(),
        "database_url_configured": bool(s.database_url),
        "message": "商用级 FDE 平台：DSH 语义分析与离线规则分析双链路，DSH 未就绪时自动降级。",
    }
