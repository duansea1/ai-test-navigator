"""AI Test Navigator FastAPI 入口：模块化组装 + 前端托管 + 生命周期管理。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path as _Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.api.reports import file_router
from app.core.config import get_settings
from app.dsh.runtime import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB 建表（含 model_configs 默认供应商种子）：失败只告警不阻塞
    try:
        from app.db.engine import init_schema

        init_schema()
        # 清理僵尸任务：上次进程退出时未到终态的任务标记中断（内存进度已丢失，不可恢复）
        from app.db import entities

        entities.fail_stale_tasks()
    except Exception as exc:
        print(f"[db] 初始化失败（服务继续，任务入库不可用）：{exc}")
    # DSH 预检：只探测可用性，失败不阻塞启动（离线规则分析兜底）
    manager.availability()
    yield
    manager.stop()


app = FastAPI(title="AI Test Navigator", version="2.0.0", lifespan=lifespan)
app.include_router(api_router)
app.include_router(file_router)

_settings = get_settings()
if (_settings.frontend_dist / "index.html").exists():
    # 新 React 前端（构建产物）
    app.mount("/assets", StaticFiles(directory=_settings.frontend_dist / "assets"), name="assets")
    _INDEX_PATH = _Path(_settings.frontend_dist / "index.html")

    def _render_index() -> str:
        try:
            ts = int((_Path(_settings.frontend_dist) / "assets" / "app.js").stat().st_mtime)
        except OSError:
            ts = 0
        html = _INDEX_PATH.read_text(encoding="utf-8")
        return html.replace(
            'href="/assets/styles.css"',
            f'href="/assets/styles.css?v={ts}"', 1
        ).replace(
            'src="/assets/app.js"',
            f'src="/assets/app.js?v={ts}"', 1
        )

    @app.get("/", response_class=HTMLResponse)
    def home() -> "Response":
        return Response(_render_index(), media_type="text/html",
                        headers={"Cache-Control": "no-store"})
else:
    # 旧单页过渡（React 前端构建后自动切换）
    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return _settings.frontend_index.read_text(encoding="utf-8")
