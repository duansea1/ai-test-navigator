"""Agent 编排域：Agent 注册表、DSH Runtime 状态、会话试运行（流式）。"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.db import entities as E
from app.dsh.agents import build_agent_prompt, get_agent, list_agents
from app.dsh.runtime import manager

router = APIRouter(tags=["agents"])


@router.get("/agents")
def agents() -> dict[str, object]:
    return {"agents": list_agents(), "runtime": manager.availability()}


@router.get("/agents/{agent_id}")
def agent_detail(agent_id: str) -> dict[str, object]:
    agent = get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} 不存在")
    return {"id": agent.id, "name": agent.name, "role": agent.role, "output_contract": agent.output_contract, "fde_module": agent.fde_module}


@router.post("/agents/{agent_id}/run")
def run_agent(agent_id: str, payload: dict[str, str]) -> dict[str, object]:
    """同步试运行一个 Agent 回合（M0 验证 DSH 链路；M2 接入完整编排）。"""
    prompt = build_agent_prompt(agent_id, payload.get("input", ""))
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} 不存在")
    result = manager.run_turn(prompt, session_id=payload.get("session_id") or None)
    return {"agent_id": agent_id, **result}


@router.get("/agents/runtime/status")
def runtime_status() -> dict[str, object]:
    return manager.availability()


# ─── 模型供应商配置管理 ──────────────────────────────────────────────────────

def _http_get_models(base_url: str, api_key: str) -> tuple[bool, Any]:
    """调用 OpenAI 兼容 /models 端点探测可用模型。返回 (ok, payload_or_error)。
    兼容 base_url 末尾带或不带 /v1 两种形态：先试 /models，404/网络错误再回退 /v1/models。"""
    if not base_url:
        return False, {"error": "未配置 API 地址"}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    last_err: Any = {"error": "未探测到可用端点"}
    for path in ("/models", "/v1/models"):
        url = base_url.rstrip("/") + path
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return True, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                last_err = json.loads(e.read().decode("utf-8"))
            except Exception:
                last_err = {"error": f"HTTP {e.code}"}
            if e.code == 401:
                return False, last_err  # 路径正确但鉴权失败，无需再试其他路径
        except Exception as exc:  # noqa: BLE001
            last_err = {"error": f"{type(exc).__name__}: {exc}"}
    return False, last_err


def _http_chat_probe(base_url: str, api_key: str, model_id: str) -> tuple[bool, Any]:
    """真实单模型连通探测：向目标模型发一条最小 chat completion，确认其可调用。

    与 _http_get_models（仅列目录）不同，本函数验证的是「这个具体模型能不能真正回答」，
    即连通 + 鉴权 + 模型存在且可推理 三者同时成立。
    """
    if not base_url:
        return False, {"error": "未配置 API 地址"}
    if not model_id:
        return False, {"error": "未指定要探测的模型 ID"}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    # 归一化 base：去掉可能尾随的 /v1，再统一补 /v1/chat/completions
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    last_err: Any = {"error": "未探测到可用端点"}
    for path in ("/v1/chat/completions", "/chat/completions"):
        url = root.rstrip("/") + path
        body = json.dumps({
            "model": model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8,
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                out = json.loads(resp.read().decode("utf-8"))
                content = ""
                try:
                    content = out["choices"][0]["message"]["content"]
                except Exception:
                    content = ""
                return True, {"data": {"model": model_id, "replied_len": len(content)}}
        except urllib.error.HTTPError as e:
            try:
                last_err = json.loads(e.read().decode("utf-8"))
            except Exception:
                last_err = {"error": f"HTTP {e.code}"}
            if e.code == 401:
                return False, last_err
        except Exception as exc:  # noqa: BLE001
            last_err = {"error": f"{type(exc).__name__}: {exc}"}
    return False, last_err


def _resolve_test_target(provider_key: str, payload: dict) -> tuple[bool, str, str, list]:
    """解析测试/拉取目标的 base_url、api_key 与 model_ids。

    优先使用前端传入的表单草稿值（改完未保存也能测）；
    草稿缺省时回退到已保存配置；均缺失则视为供应商不存在。
    """
    payload = payload or {}
    base_url = str(payload.get("base_url") or "").strip()
    api_key = str(payload.get("api_key") or "").strip()
    model_ids = [str(m).strip() for m in (payload.get("model_ids") or []) if str(m).strip()]
    if base_url:
        # 草稿只改了 URL、未重填 key 时，优先回退到该 provider 已保存的 key，
        # 而非 DeepSeek 默认 key（否则 baoyun 等第三方渠道会 401）。
        if not api_key:
            row = E.get_model_config_full(provider_key)
            if row:
                api_key = row.get("api_key") or ""
                if not model_ids:
                    model_ids = row.get("model_ids") or []
        api_key = api_key or get_settings().dsh_resolved_api_key
        return True, base_url, api_key, model_ids
    row = E.get_model_config_full(provider_key)
    if row is None:
        return False, "", "", []
    return (True, row.get("base_url") or "",
            row.get("api_key") or get_settings().dsh_resolved_api_key,
            row.get("model_ids") or [])


@router.get("/agents/runtime/config")
def runtime_config() -> dict[str, object]:
    """可用模型列表 + 当前配置（前端模型切换器数据源）。"""
    av = manager.availability()
    return {
        "models": manager.available_models(),
        "current": {"provider_key": av.get("provider_key"), "model": av.get("model")},
        "configs": E.list_model_configs(),
    }


@router.post("/agents/runtime/config")
def runtime_set_config(payload: dict[str, str]) -> dict[str, object]:
    """运行时切换供应商配置（立即生效于后续新回合，无需重启服务）。"""
    provider_key = str(payload.get("provider_key") or "").strip()
    if provider_key:
        if E.get_model_config_full(provider_key) is None:
            raise HTTPException(400, f"供应商配置不存在：{provider_key}")
        return manager.reconfigure(provider_key=provider_key)
    model = str(payload.get("model") or "").strip()
    if model:
        return manager.reconfigure(provider_key=model)
    return manager.availability()


@router.get("/agents/runtime/config/models")
def list_models() -> dict[str, object]:
    av = manager.availability()
    return {"models": manager.available_models(), "configs": E.list_model_configs(),
            "current_key": av.get("provider_key")}


# ─── 子路由（具体路径在前，避免被 {provider_key:path} 贪婪吞掉） ────────

@router.post("/agents/runtime/config/models/restore-defaults")
def restore_defaults() -> dict[str, object]:
    E.restore_default_model_configs()
    return {"ok": True, "models": manager.available_models()}


@router.post("/agents/runtime/config/models/{provider_key:path}/default")
def set_default(provider_key: str) -> dict[str, object]:
    if E.get_model_config_full(provider_key) is None:
        raise HTTPException(404, "供应商配置不存在")
    E.set_default_model_config(provider_key)
    return {"ok": True}


@router.post("/agents/runtime/config/models/{provider_key:path}/test")
def test_model(provider_key: str, payload: dict[str, Any] | None = None) -> dict[str, object]:
    ok, base_url, api_key, model_ids = _resolve_test_target(provider_key, payload or {})
    if not ok:
        raise HTTPException(404, f"供应商配置不存在：{provider_key}")
    if not model_ids:
        return {"ok": False,
                "error": "未配置模型 ID，无法测试单模型连通（请先填写至少一个模型 ID，或在编辑表单中拉取模型清单）"}
    ok, data = _http_chat_probe(base_url, api_key, model_ids[0])
    return {"ok": ok, "data": (data.get("data") if isinstance(data, dict) else data),
            "error": (data.get("error") if not ok else None)}


@router.post("/agents/runtime/config/models/{provider_key:path}/fetch-available")
def fetch_available(provider_key: str, payload: dict[str, Any] | None = None) -> dict[str, object]:
    ok, base_url, api_key, _ = _resolve_test_target(provider_key, payload or {})
    if not ok:
        raise HTTPException(404, f"供应商配置不存在：{provider_key}")
    ok, data = _http_get_models(base_url, api_key)
    if not ok:
        msg = data.get("error") if isinstance(data, dict) else str(data)
        raise HTTPException(502, f"供应商探测失败：{msg}")
    sample = data.get("data", []) if isinstance(data, dict) else []
    model_ids = [m.get("id") for m in sample if isinstance(m, dict) and m.get("id")]
    return {"ok": True, "model_ids": model_ids}


# ─── 通用路由（catch-all，放在最后） ─────────────────────────────────

@router.post("/agents/runtime/config/models/{provider_key:path}")
def upsert_model(provider_key: str, payload: dict[str, Any]) -> dict[str, object]:
    display_name = str(payload.get("display_name") or provider_key).strip()
    api_key = str(payload.get("api_key") or "").strip() or None
    base_url = str(payload.get("base_url") or "").strip() or None
    protocol = str(payload.get("protocol") or "openai-completions").strip()
    model_ids = payload.get("model_ids") or []
    if isinstance(model_ids, str):
        model_ids = [m.strip() for m in model_ids.split(",") if m.strip()]
    model_ids = [str(m).strip() for m in model_ids if str(m).strip()]
    if not model_ids:
        raise HTTPException(400, "至少需要一个模型 ID")
    is_custom = bool(payload.get("is_custom", True))
    enabled = payload.get("enabled", True)
    E.upsert_model_config(provider_key, display_name, api_key, base_url, protocol,
                          model_ids, is_custom, bool(enabled))
    return {"ok": True, "configs": E.list_model_configs()}


@router.delete("/agents/runtime/config/models/{provider_key:path}")
def delete_model(provider_key: str) -> dict[str, object]:
    row = E.get_model_config_full(provider_key)
    if row is None:
        raise HTTPException(404, "供应商配置不存在")
    if row.get("is_default"):
        raise HTTPException(400, "默认供应商不可删除")
    E.delete_model_config(provider_key)
    return {"ok": True}


@router.post("/agents/runtime/start")
def runtime_start() -> dict[str, object]:
    ok = manager.start()
    return {"started": ok, **manager.availability()}


@router.post("/agents/runtime/stop")
def runtime_stop() -> dict[str, object]:
    manager.stop()
    return {"started": False, **manager.availability()}
