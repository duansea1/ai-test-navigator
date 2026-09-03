"""DSH 长驻 Runtime 管理器：源码路径注入、懒启动、健康检查、优雅关闭。

设计要点：
- SDK 以源码方式集成（sys.path 注入 deepseek-harness 的 python/sdk/src 与 sdk-runtime/src），
  git pull 即升级，无需 pip 安装。
- Runtime 子进程长驻复用（DeepSeekHarness 实例跨请求复用），崩溃后下次调用自动重启。
- 所有失败路径都显式暴露状态，不抛异常阻断服务（离线规则分析兜底）。
"""
from __future__ import annotations

import hashlib
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

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
        self._preferred_model: str | None = None  # 用户在该供应商下选定的模型 ID
        self._selection_loaded = False  # 持久化选择是否已从 DB 懒加载
        # 运行时代际物理会话隔离（2026-09-02 修复 persisted log collision）：
        # 调用方传的是逻辑会话 ID（conv-xxx--qa / {task_id}--{agent_id}），用于
        # 路由语义与调试；Runtime 内部把它映射成 runtime-scoped 物理 DSH ID 再喂给 SDK。
        # 同一存活 Runtime 内同一逻辑 ID → 同一物理 ID（保留多轮 DSH 上下文）；
        # Runtime 被 stop/重配/异常重建/进程重启后生成新代际 → 新物理 ID，绝不把
        # 新 live session 当作旧持久化日志续写（DSH coordinator 正确拒绝 id collision）。
        # 跨 Runtime 的对话连续性由 router._history_block() 从 DB 注入最近消息承担。
        self._runtime_gen: str = ""  # 当前活 Runtime 的代际标识（空=未启动）
        self._session_map: dict[str, str] = {}  # 逻辑 ID → 物理 DSH ID

    # ---------- 持久化选择（2026-09-01 修「重启后选型回默认」） ----------

    ACTIVE_PROVIDER_KEY = "active_provider"
    ACTIVE_MODEL_KEY = "active_model"

    def _load_selection(self) -> None:
        """从 app_settings 懒加载用户上次选中的供应商/模型（重启后仍生效）。"""
        if self._selection_loaded:
            return
        self._selection_loaded = True
        try:
            from app.db import entities as E  # 延迟导入避免循环

            if self._preferred_provider_key is None:
                self._preferred_provider_key = E.get_setting(self.ACTIVE_PROVIDER_KEY)
            if self._preferred_model is None:
                self._preferred_model = E.get_setting(self.ACTIVE_MODEL_KEY)
        except Exception:
            pass  # DB 不可用：沿用内存/默认

    def _persist_selection(self) -> None:
        try:
            from app.db import entities as E

            if self._preferred_provider_key:
                E.set_setting(self.ACTIVE_PROVIDER_KEY, self._preferred_provider_key)
            if self._preferred_model:
                E.set_setting(self.ACTIVE_MODEL_KEY, self._preferred_model)
        except Exception:
            pass  # 持久化失败不阻断切换（本次会话仍生效）

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
        self._load_selection()
        cfg = self._resolve_provider_config() or {}
        return {
            "ready": s.dsh_ready,
            # 2026-08-25 铁律：ready 仅是静态展示（源码+Key+载体齐备）；
            # callable 才是真相——start() 不做 Key 前置拦截，DSH 凭据库可能持有 Key。
            "callable": s.dsh_source_available and (s.dsh_mode != "node" or s.dsh_node_carrier_available),
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

    # 第三方网关已知 max_tokens 上限（实测）：DSH 默认 256_000 会被网关 400 拒掉。
    # 官方 API（api.deepseek.com）不在此列，保持 SDK 默认上限。
    _GATEWAY_MAX_TOKENS = 131_072
    _GATEWAY_HOSTS = ("ai-api.baoyun.com",)

    def _max_tokens_for(self, base_url: str | None) -> int | None:
        """按 base_url 判断是否需要钳制 max_tokens：宝云等网关返回 None 之外的上限。"""
        if not base_url:
            return None
        host = (base_url or "").lower()
        if any(h in host for h in self._GATEWAY_HOSTS):
            return self._GATEWAY_MAX_TOKENS
        return None

    @staticmethod
    def _normalize_base_url(base: str | None) -> str | None:
        """base_url 归一化（2026-09-01 实测踩坑）。

        llm-deepseek 适配器直接请求 `{baseURL}/chat/completions`（adapter.ts），
        即 baseURL 需自带版本前缀（DeepSeek 官方默认 https://api.deepseek.com/v1）。
        第三方网关（如 ai-api.baoyun.com）只服务 /v1/chat/completions——配置里
        只写域名时 DSH 会打到裸 /chat/completions → HTTP 404，且此前错误被吞成
        「模型未返回内容」。规则：URL 无路径（纯域名）时自动补 /v1；
        带路径的（/v1、/api 等自定义网关）尊重原样。"""
        if not base:
            return base
        from urllib.parse import urlparse
        b = base.rstrip("/")
        parsed = urlparse(b)
        if not parsed.path:
            b += "/v1"
        return b

    def _resolve_provider_config(self) -> dict[str, Any] | None:
        """从 model_configs 表解析当前要用的供应商配置（优先选中项，否则默认项）。

        回退策略：DB 无配置/未建表时回退到 settings 凭证（兼容环境变量/凭据文件场景）。
        api_key 允许为空：DSH 凭据库（~/.dsh/.credentials.yaml）可能持有 Key，
        由 SDK 自行解析——平台不做「无 Key 就拒绝启动」的前置拦截。
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

            self._load_selection()
            key = self._preferred_provider_key
            row = E.get_model_config_full(key) if key else None
            if row is None:
                # 持久化选中的供应商已被删除/恢复默认清掉：回落默认配置
                row = E.get_default_model_config()
        except Exception:
            # 表未建或 DB 不可用：回退 settings 凭证
            return fallback
        if row is None:
            return fallback
        model_ids = row.get("model_ids") or [self.settings.dsh_model]
        # 模型选择：用户在该供应商下点选的模型优先（须仍在目录中，防止配置
        # 编辑后残留失效选择），否则目录首个
        model_id = (self._preferred_model if self._preferred_model in model_ids
                    else (model_ids[0] if model_ids else self.settings.dsh_model))
        return {
            "provider": self.settings.dsh_provider,  # DSH 仅接受 deepseek 供应商名
            "model_id": model_id,
            "api_key": row.get("api_key") or self.settings.dsh_resolved_api_key,
            "base_url": self._normalize_base_url(
                row.get("base_url") or self.settings.deepseek_base_url or "https://api.deepseek.com/v1"),
            "protocol": row.get("protocol", "openai-completions"),
        }

    # ---------- 生命周期 ----------

    def start(self) -> bool:
        """懒启动 Runtime：不做静态前置拦截（2026-08-25 用户铁律）——尽可能尝试调起模型。

        凭据解析优先级：model_configs 表（用户可能在设置页存过 Key）→ 环境变量/凭据文件
        → DSH 自身凭据库（api_key=None 时 SDK 自行解析）。静态 dsh_ready 仅作状态展示，
        不作为调用闸门；只有真正启动失败（源码缺失/载体缺失/启动抛错）才返回 False。
        """
        with self._lock:
            if self._harness is not None:
                return True
            if not self.settings.dsh_source_available:
                self.last_error = "DSH 源码不可用（deepseek-harness 仓库未找到）"
                return False
            try:
                cfg = self._resolve_provider_config()
                if not cfg or not cfg.get("model_id"):
                    self.last_error = "无可用模型供应商配置"
                    return False
                if self.settings.dsh_mode == "node" and not self.settings.dsh_node_carrier_available:
                    self.last_error = "node 载体未构建（scripts/build-dsh-node-carrier.mjs）"
                    return False
                # Key 缺失不拦截：api_key=None 时 SDK 自行从 DSH 凭据库解析
                #（2026-08-25 用户铁律：尽可能调起模型，不前置拒绝）。
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
                    # max_tokens 上限钳制（2026-09-02 实测踩坑）：DSH llm-deepseek
                    # 默认 256_000（adapter.ts DEFAULT_MAX_TOKENS），第三方网关
                    # （如 ai-api.baoyun.com）校验 [1, 131072] 直接 400——报错曾
                    # 被吞成「模型未返回内容」。官方 API 上限更高不受影响。
                    max_tokens=self._max_tokens_for(cfg["base_url"]),
                    # 满血组合：subagent/fork/claude-code + workflow + skills + fs 全套
                    cordis=str(self.settings.dsh_cordis) if self.settings.dsh_cordis.exists() else None,
                    # 内置 cordis.yml 未挂载 credentials-local 插件，
                    # 凭据经子进程环境变量注入（环境变量优先，DSH 凭据库兜底）。
                    api_key=cfg["api_key"] or None,
                    base_url=cfg["base_url"] or None,
                )
                self._harness.start()
                # 新 Runtime 代际：本代际内的物理会话 ID 与旧持久化日志不会碰撞。
                self._runtime_gen = uuid4().hex[:8]
                self._session_map = {}
                self.started_at = datetime.now()
                self.last_error = None
                return True
            except Exception as exc:  # Runtime 启动失败不阻断服务
                self._harness = None
                self._runtime_gen = ""
                self._session_map = {}
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
            # 清代际与映射：下次懒启动生成新代际，物理 ID 不复用旧 Runtime 的，
            # 避免再次撞上旧 .dsh-sessions 持久化日志（collision 根因）。
            self._runtime_gen = ""
            self._session_map = {}
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
        """运行时切换供应商配置与模型（立即生效于后续新回合）。

        provider_key：model_configs 的一条；model：该供应商目录内的模型 ID
        （仅换模型不换供应商时传 model 即可）。选择持久化到 app_settings——
        2026-09-01 修复「重启后选型回默认」：此前选择只在内存，进程一重启
        就回到 is_default 配置。持久化失败不阻断（本次运行仍生效）。
        """
        changed: list[str] = []
        self._load_selection()
        if provider_key and provider_key != self._preferred_provider_key:
            self._preferred_provider_key = provider_key
            # 换供应商时模型若不属于新供应商目录则清掉（由目录首个顶上）
            changed.append("provider")
        if model and model != self._preferred_model:
            self._preferred_model = model
            changed.append("model")
        if changed:
            # 校正模型选择仍在当前供应商目录内
            try:
                from app.db import entities as E

                key = self._preferred_provider_key
                row = E.get_model_config_full(key) if key else E.get_default_model_config()
                ids = (row or {}).get("model_ids") or []
                if self._preferred_model and ids and self._preferred_model not in ids:
                    self._preferred_model = None
            except Exception:
                pass
            self._persist_selection()
            self.stop()  # 下次 run_turn 懒启动时以新配置拉起
        return {"changed": changed, **self.availability()}

    # ---------- 会话 ----------

    def _physical_session_id(self, logical_id: str | None) -> str | None:
        """逻辑会话 ID → runtime-scoped 物理 DSH ID（2026-09-02 collision 修复）。

        - 无 logical_id（一次性调用）：返回 None，沿用 SDK 原有随机 session 行为。
        - 同一存活 Runtime 内，同一 logical_id 始终映射到同一物理 ID，保留多轮
          DSH 上下文；Runtime 重建后 _runtime_gen 变更 → 新物理 ID，绝不撞旧日志。
        - 物理 ID = 代际前缀 + logical_id 的稳定短哈希，既可调试溯源，又避免
          业务会话 ID（可能含 conv-/-- 等字符）超长或与旧日志同名。
        """
        if not logical_id:
            return None
        if not self._runtime_gen:  # Runtime 未起（理论不达此分支，防御）
            self._runtime_gen = uuid4().hex[:8]
        pid = self._session_map.get(logical_id)
        if pid:
            return pid
        digest = hashlib.sha1(logical_id.encode("utf-8")).hexdigest()[:10]
        pid = f"r{self._runtime_gen}-{digest}"
        self._session_map[logical_id] = pid
        return pid

    def run_turn(self, prompt: str, session_id: str | None = None,
                 on_event: Any | None = None) -> dict[str, Any]:
        """执行一个会话回合，返回结构化结果；失败时返回 fallback 标记。

        on_event：实时事件回调（SDK on_notification 桥接）。
        回调收到 DSH 原始 session 事件 dict（type/data），供聊天式流式输出消费；
        回调异常不阻断主流程。

        session_id：**逻辑**会话 ID（conv-xxx--qa / {task_id}--{agent_id}），
        由调用方用于路由语义。Runtime 内部经 _physical_session_id() 转成
        runtime-scoped 物理 ID 喂给 SDK——避免后端重启/Runtime 重建后用同一
        逻辑 ID 新建 live session 撞上旧持久化日志（DSH id collision）。
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

        physical_id = self._physical_session_id(session_id)
        try:
            result = self._harness.run(prompt, session_id=physical_id, on_notification=_notify)
            sid = result.session_id
            final = (result.final_response or "").strip()
            finish = result.finish_reason
            self.sessions[sid] = {
                "session_id": sid,
                "logical_id": session_id,
                "physical_id": physical_id,
                "finish_reason": finish,
                "turns": self.sessions.get(sid, {}).get("turns", 0) + 1,
            }
            # 模型级错误显式化（2026-09-01 修复「模型未返回内容」黑盒）：
            # SDK 的 run() 不因模型错误抛异常——404/配额/超时等表现为
            # finish_reason=error + final_response=""。此前被当成 status=ok
            # 返回空串，上游只能猜「DSH 不可用」或显示「模型未返回内容」，
            # 真实原因（如切了不存在的模型名）完全不可见。现在提取
            # turn/end 事件里的错误信息，status=error + message 随行。
            if finish == "error" or not final:
                detail = _turn_error(result.events) or f"finish_reason={finish or 'unknown'}，模型无文本输出"
                self.last_error = detail
                return {"status": "error", "message": detail,
                        "session_id": sid, "finish_reason": finish,
                        "final_response": "", "event_count": len(result.events)}
            return {
                "status": "ok",
                "session_id": sid,
                "final_response": result.final_response,
                "finish_reason": finish,
                "event_count": len(result.events),
            }
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._harness = None  # 下次调用自动重启
            # 清代际与映射：重建 Runtime 后用新物理 ID，不再撞旧持久化日志。
            self._runtime_gen = ""
            self._session_map = {}
            return {"status": "fallback", "message": self.last_error}


def _turn_error(events: list[Any]) -> str | None:
    """从回合事件里提取模型错误描述（turn/end 的 reason.error）。"""
    for event in reversed(events or []):
        if not isinstance(event, dict) or event.get("type") != "turn/end":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        reason = data.get("reason") if isinstance(data.get("reason"), dict) else {}
        if reason.get("kind") != "error":
            return None
        err = reason.get("error") if isinstance(reason.get("error"), dict) else {}
        msg = str(err.get("message") or err.get("code") or "").strip()
        return msg or "模型调用出错（未携带错误详情）"
    return None


manager = DshRuntimeManager()
