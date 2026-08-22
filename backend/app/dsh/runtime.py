"""DSH 长驻 Runtime 管理器：源码路径注入、懒启动、健康检查、优雅关闭。

设计要点：
- SDK 以源码方式集成（sys.path 注入 deepseek-harness 的 python/sdk/src 与 sdk-runtime/src），
  git pull 即升级，无需 pip 安装。
- Runtime 子进程长驻复用（DeepSeekHarness 实例跨请求复用），崩溃后下次调用自动重启。
- 所有失败路径都显式暴露状态，不抛异常阻断服务（离线规则分析兜底）。
"""
from __future__ import annotations

import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings


class DshRuntimeManager:
    """单例管理器：持有 DeepSeekHarness 实例与会话表。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._harness: Any | None = None
        self._lock = threading.Lock()
        self.sessions: dict[str, dict[str, Any]] = {}
        self.last_error: str | None = None
        self.started_at: datetime | None = None
        self._preferred_provider_key: str | None = None  # 用户选定的供应商配置 key

    # ---------- 可用性 ----------

    def _inject_source_paths(self) -> None:
        for src in (self.settings.dsh_sdk_src, self.settings.dsh_runtime_src):
            if str(src) not in sys.path:
                sys.path.insert(0, str(src))

    def _import_harness(self) -> Any:
        self._inject_source_paths()
        import deepseek_harness  # noqa: PLC0415 源码路径注入后才能导入

        return deepseek_harness

    def availability(self) -> dict[str, Any]:
        s = self.settings
        cfg = self._resolve_provider_config() or {}
        return {
            "ready": s.dsh_ready,
            "source_available": s.dsh_source_available,
            "node_carrier_available": s.dsh_node_carrier_available,
            "mode": s.dsh_mode,
            "api_key_configured": bool(cfg.get("api_key")),
            "provider": cfg.get("provider"),
            "model": cfg.get("model_id"),
            "provider_key": self._preferred_provider_key,
            "running": self._harness is not None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "active_sessions": len(self.sessions),
            "last_error": self.last_error,
        }

    # ---------- 供应商配置解析 ----------

    def _resolve_provider_config(self) -> dict[str, Any] | None:
        """从 model_configs 表解析当前要用的供应商配置（优先选中项，否则默认项）。

        回退策略：DB 无配置/未建表时回退到 settings 凭证（兼容环境变量/凭据文件场景）。
        """
        fallback = {
            "provider": self.settings.dsh_provider,
            "model_id": self.settings.dsh_model,
            "api_key": self.settings.dsh_resolved_api_key,
            "base_url": self.settings.deepseek_base_url or "https://api.deepseek.com/v1",
            "protocol": "openai-completions",
        }
        try:
            from app.db import entities as E  # 延迟导入避免循环

            key = self._preferred_provider_key
            row = E.get_model_config_full(key) if key else E.get_default_model_config()
        except Exception:
            # 表未建或 DB 不可用：回退 settings 凭证
            return fallback
        if row is None:
            return fallback
        model_ids = row.get("model_ids") or [self.settings.dsh_model]
        return {
            "provider": self.settings.dsh_provider,  # DSH 仅接受 deepseek 供应商名
            "model_id": model_ids[0] if model_ids else self.settings.dsh_model,
            "api_key": row.get("api_key") or self.settings.dsh_resolved_api_key,
            "base_url": row.get("base_url") or self.settings.deepseek_base_url or "https://api.deepseek.com/v1",
            "protocol": row.get("protocol", "openai-completions"),
        }

    # ---------- 生命周期 ----------

    def start(self) -> bool:
        """懒启动 Runtime；失败时记录原因并返回 False（调用方走规则分析兜底）。"""
        if not self.settings.dsh_ready:
            self.last_error = "DSH 未就绪（源码/node 载体/API Key 缺失）"
            return False
        with self._lock:
            if self._harness is not None:
                return True
            try:
                cfg = self._resolve_provider_config()
                if not cfg or not cfg.get("model_id"):
                    self.last_error = "无可用模型供应商配置"
                    return False
                dh = self._import_harness()
                import os

                os.environ["DSH_RUNTIME_MODE"] = self.settings.dsh_mode
                # Skills 目录注入：cordis.yml 的 skill-filesystem customSkillDirs
                os.environ["DSH_CUSTOM_SKILL_DIRS"] = self.settings.dsh_skill_dirs
                self.settings.dsh_session_root.mkdir(parents=True, exist_ok=True)
                self._harness = dh.DeepSeekHarness(
                    provider=cfg["provider"],
                    model=cfg["model_id"],
                    cwd=str(self.settings.workspace),
                    session_root=str(self.settings.dsh_session_root),
                    # 满血组合：subagent/fork/claude-code + workflow + skills + fs 全套
                    cordis=str(self.settings.dsh_cordis) if self.settings.dsh_cordis.exists() else None,
                    # 内置 cordis.yml 未挂载 credentials-local 插件，
                    # 凭据经子进程环境变量注入（环境变量优先，DSH 凭据库兜底）。
                    api_key=cfg["api_key"] or None,
                    base_url=cfg["base_url"] or None,
                )
                self._harness.start()
                self.started_at = datetime.now()
                self.last_error = None
                return True
            except Exception as exc:  # Runtime 启动失败不阻断服务
                self._harness = None
                self.last_error = f"{type(exc).__name__}: {exc}"
                return False

    def stop(self) -> None:
        with self._lock:
            if self._harness is not None:
                try:
                    self._harness.close()
                except Exception:
                    pass
                self._harness = None
            self.started_at = None

    def restart(self) -> bool:
        self.stop()
        return self.start()

    # ---------- 运行时配置 ----------

    AVAILABLE_MODELS: list[dict[str, str]] = [
        {"id": "deepseek-v4-flash", "label": "deepseek-v4-flash · 快速（默认）"},
        {"id": "deepseek-chat", "label": "deepseek-chat · 通用对话"},
        {"id": "deepseek-reasoner", "label": "deepseek-reasoner · 深度推理"},
        {"id": "deepseek-coder", "label": "deepseek-coder · 代码增强"},
    ]

    def available_models(self) -> list[dict[str, str]]:
        """从 model_configs 表导出可选模型（enabled 的供应商配置）。"""
        from app.db import entities as E

        try:
            rows = E.list_model_configs()
        except Exception:
            return self.AVAILABLE_MODELS
        out = []
        for r in rows:
            if not r.get("enabled"):
                continue
            mids = r.get("model_ids") or []
            label = r.get("display_name", r.get("provider_key", ""))
            if mids:
                label = f"{label} · {mids[0]}"
            out.append({"id": r["provider_key"], "label": label})
        return out or self.AVAILABLE_MODELS

    def reconfigure(self, provider_key: str | None = None, model: str | None = None) -> dict[str, Any]:
        """运行时切换供应商配置（provider_key 指向 model_configs 的一条）。

        立即生效于后续新回合（复用中的旧会话回合不受影响）。
        """
        changed: list[str] = []
        if provider_key and provider_key != self._preferred_provider_key:
            self._preferred_provider_key = provider_key
            changed.append("provider")
        if changed:
            self.stop()  # 下次 run_turn 懒启动时以新模型拉起
        return {"changed": changed, **self.availability()}

    # ---------- 会话 ----------

    def run_turn(self, prompt: str, session_id: str | None = None,
                 on_event: Any | None = None) -> dict[str, Any]:
        """执行一个会话回合，返回结构化结果；失败时返回 fallback 标记。

        on_event：实时事件回调（SDK on_notification 桥接）。
        回调收到 DSH 原始 session 事件 dict（type/data），供聊天式流式输出消费；
        回调异常不阻断主流程。
        """
        if not self.start():
            return {"status": "fallback", "message": self.last_error or "DSH 未就绪"}

        def _notify(notification: Any) -> None:
            if on_event is None:
                return
            try:
                if getattr(notification, "method", "") != "session.event":
                    return
                event = (notification.payload or {}).get("event")
                if isinstance(event, dict):
                    on_event(event)
            except Exception:  # noqa: BLE001 回调失败不影响回合执行
                pass

        try:
            result = self._harness.run(prompt, session_id=session_id, on_notification=_notify)
            sid = result.session_id
            self.sessions[sid] = {
                "session_id": sid,
                "finish_reason": result.finish_reason,
                "turns": self.sessions.get(sid, {}).get("turns", 0) + 1,
            }
            return {
                "status": "ok",
                "session_id": sid,
                "final_response": result.final_response,
                "finish_reason": result.finish_reason,
                "event_count": len(result.events),
            }
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._harness = None  # 下次调用自动重启
            return {"status": "fallback", "message": self.last_error}


manager = DshRuntimeManager()
