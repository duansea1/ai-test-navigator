"""API 路由聚合：一个菜单域一个模块，新增功能即新增模块。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api import agents, dashboard, evidence, projects, reports, requirements, settings, testing

api_router = APIRouter(prefix="/api")
api_router.include_router(dashboard.router)
api_router.include_router(requirements.router)
api_router.include_router(projects.router)
api_router.include_router(agents.router)
api_router.include_router(testing.router)
api_router.include_router(reports.router)
api_router.include_router(evidence.router)
api_router.include_router(settings.router)

__all__ = ["api_router"]
