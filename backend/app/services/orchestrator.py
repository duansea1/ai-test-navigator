"""分析任务编排：规则分析（离线保底）+ DSH 8-Agent 语义分析流水线。

流水线（每 Agent 独立 DSH 会话，阶段失败降级跳过）：
  1. requirement-analyst  需求结构化          → requirements 表
  2. project-scout        项目相关性判断      → 内存（供后续阶段）
  3. code-locator         代码证据定位        → code_evidence 表（可调用 fs/grep 工具实查源码）
  4. call-chain           调用链/影响范围     → impact_scopes 表
  5. impl-reviewer        逐条实现审查        → 内存（与 7 合并）
  6. test-designer        五类测试用例        → test_cases 表
  7. quality-judge        质量裁决            → assessments 表（与 5 合并入库）
  8. report-writer        三视角报告摘要      → reports 表

进度模型：内存 task_progress（版本号，SSE 消费）+ DB 状态双写。
降级链路：DSH 不可用 → 规则分析 + 规则解析需求入库（保留分析能力，不阻塞）。
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from app.core.config import get_settings
from app.dsh import agents as agent_registry
from app.dsh.runtime import manager as dsh_manager
from app.db import entities
from app.services.analyzer import NavigatorAnalyzer
from app.services.reporter import write_reports

# task_id → 进度快照（含版本号，SSE 按版本增量推送）
_progress: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()

# task_id → 聊天式活动流（Agent 工具调用/模型输出实时增量，SSE 按 seq 推送）
_activity: dict[str, list[dict[str, Any]]] = {}
_act_seq: dict[str, int] = {}

# 8-Agent 阶段名（这些阶段的进度事件由 Agent 卡片承载，不推系统消息）
_AGENT_STAGES = {"requirement-analyst", "project-scout", "code-locator", "call-chain",
                 "impl-reviewer", "test-designer", "quality-judge", "report-writer"}


def snapshot(task_id: str) -> dict[str, Any]:
    """当前进度快照（SSE 起点或前端主动查询）。"""
    with _lock:
        snap = dict(_progress.get(task_id, {}))
    if not snap:
        task = entities.get_task(task_id)
        if task:
            snap = {"version": 0, "stage": task["stage"], "progress": task["progress"],
                    "message": task["message"], "status": task["status"], "events": []}
    return snap


def activity_items(task_id: str) -> list[dict[str, Any]]:
    """聊天活动流全量（内存优先；进程重启后从 DB 重建粗粒度时间线）。"""
    with _lock:
        items = _activity.get(task_id)
    if items:
        return list(items)
    rebuilt: list[dict[str, Any]] = []
    try:
        for ev in entities.list_dsh_events(task_id):
            p = ev.get("payload") or {}
            agent = agent_registry.get_agent(ev.get("session_id", ""))
            rebuilt.append({
                "seq": len(rebuilt) + 1,
                "time": str(ev.get("created_at", ""))[-8:],
                "agent": ev.get("session_id", ""),
                "agent_name": agent.name if agent else ev.get("session_id", ""),
                "kind": ev.get("event_type", ""),
                **({k: v for k, v in p.items() if k in ("ok", "summary", "preview", "model", "provider")}),
            })
        if rebuilt:
            with _lock:
                _activity[task_id] = rebuilt
                _act_seq[task_id] = len(rebuilt)
    except Exception:  # DB 不可用时空时间线
        pass
    return rebuilt


def _push_activity(task_id: str, agent_id: str, kind: str, **extra: Any) -> None:
    """追加一条活动事件（内存 + Agent 生命周期关键事件落库）。"""
    agent = agent_registry.get_agent(agent_id)
    with _lock:
        seq = _act_seq.get(task_id, 0) + 1
        _act_seq[task_id] = seq
        item = {"seq": seq, "time": datetime.now().strftime("%H:%M:%S"),
                "agent": agent_id, "agent_name": agent.name if agent else agent_id,
                "kind": kind, **extra}
        _activity.setdefault(task_id, []).append(item)
    if kind in ("agent_start", "agent_end"):
        try:
            entities.save_dsh_event(task_id, agent_id, kind,
                                    {k: v for k, v in extra.items()
                                     if k in ("ok", "summary", "preview", "model", "provider")})
        except Exception:
            pass


def _emit(task_id: str, stage: str, progress: int, message: str, **extra: Any) -> None:
    """推进进度：内存版本 + DB 状态；非 Agent 阶段同步推聊天系统消息。"""
    with _lock:
        cur = _progress.setdefault(task_id, {"version": 0, "events": []})
        cur["version"] += 1
        cur.update({"stage": stage, "progress": progress, "message": message, **extra})
        cur["events"].append({"version": cur["version"], "stage": stage,
                              "progress": progress, "message": message,
                              "time": datetime.now().strftime("%H:%M:%S")})
    entities.update_task(task_id, stage=stage, progress=progress, message=message)
    if stage not in _AGENT_STAGES:
        _push_activity(task_id, "system", "stage", stage=stage, progress=progress, text=message)


def create_task(title: str, source_text: str, projects: str, branch: str, workspace: str, mode: str = "auto") -> str:
    """入库并异步执行；返回 task_id。mode: auto/qa/analyze/full。"""
    task_id = entities.create_task(title, source_text, projects, branch, workspace)
    with _lock:
        _progress[task_id] = {"version": 0, "stage": "pending", "progress": 0,
                              "message": "任务已创建", "status": "pending", "events": []}
    t = threading.Thread(target=_run_task, args=(task_id, mode), daemon=True, name=f"task-{task_id}")
    t.start()
    return task_id


# ─── JSON 提取（模型输出容错解析）────────────────────────────────────────────

_JSON_KEYS = ("items", "projects", "evidence", "chains", "assessments", "cases", "verdicts", "views")


def _extract_json(text: str, keys: tuple[str, ...] = _JSON_KEYS) -> Any:
    """从模型输出提取结构化 JSON：兼容 ```json 围栏 / 裸 JSON / 首尾噪声 / JSON 后尾随多块输出。
    返回 keys 依序第一个命中的数组（或 dict），失败返回 None。"""
    candidates: list[Any] = []
    # 1) 围栏块
    for raw in re.findall(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL):
        try:
            candidates.append(json.loads(raw))
        except (ValueError, TypeError):
            continue
    # 2) 裸 JSON：raw_decode 解析首个完整值（容忍 JSON 后的说明文字或多块 JSON）
    decoder = json.JSONDecoder()
    for ch in ("{", "["):
        idx = text.find(ch)
        while idx >= 0:
            try:
                data, _ = decoder.raw_decode(text[idx:])
                candidates.append(data)
                break
            except ValueError:
                idx = text.find(ch, idx + 1)
    for data in candidates:
        if isinstance(data, dict):
            for key in keys:
                if isinstance(data.get(key), list) and data[key]:
                    return data[key]
            if any(k in data for k in keys):
                return data
        elif isinstance(data, list) and data:
            return data
    return None


def _extract_items(text: str) -> list[dict[str, Any]] | None:
    """需求条目提取（M1 接口，保持兼容）。"""
    items = _extract_json(text, keys=("items",))
    if not isinstance(items, list):
        return None
    return [
        {
            "id": str(it.get("id") or f"REQ-{i + 1:02d}"),
            "title": str(it.get("title", ""))[:500],
            "description": str(it.get("description", "")),
            "priority": str(it.get("priority", "P1")),
            "acceptance_criteria": [str(a) for a in it.get("acceptance_criteria", []) if a],
        }
        for i, it in enumerate(items)
        if isinstance(it, dict)
    ]


# ─── Agent 阶段执行 ──────────────────────────────────────────────────────────

def _tool_args_preview(args: Any) -> str:
    """工具调用参数紧凑预览（聊天时间线展示用）。"""
    if args in (None, "", {}, []):
        return ""
    try:
        s = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(args)
    return s[:260]


def _message_text(event: dict) -> str:
    """assistant/message 事件提取文本块。"""
    data = event.get("data") or {}
    message = data.get("message") if isinstance(data.get("message"), dict) else data
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    return "".join(
        str(b.get("text", "")) for b in content
        if isinstance(b, dict) and b.get("type") == "text"
    ).strip()


def _activity_handler(task_id: str, agent_id: str):
    """DSH 原始事件 → 聊天活动（只保留有展示价值的：工具调用/模型文本）。"""
    agent = agent_registry.get_agent(agent_id)
    name = agent.name if agent else agent_id

    def handler(event: dict) -> None:
        etype = str(event.get("type", ""))
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if etype == "tool/call":
            _push_activity(task_id, agent_id, "tool",
                           tool=str(data.get("name", "?"))[:60],
                           detail=_tool_args_preview(data.get("arguments")))
        elif etype == "assistant/message":
            text = _message_text(event)
            if text:
                _push_activity(task_id, agent_id, "text", text=text[:1500])
        elif etype == "skill":  # Skill 调用（如 skill-filesystem 装载）
            _push_activity(task_id, agent_id, "skill",
                           tool=str(data.get("name", "skill"))[:60],
                           detail=_tool_args_preview(data.get("input", data)))
    return handler


def _run_agent(task_id: str, agent_id: str, payload: str) -> tuple[Any, dict | None]:
    """执行单个 Agent 回合（独立会话，防上下文串味）。

    聊天时间线：agent_start（含模型信息）→ tool/text 增量 → 由调用方推 agent_end。
    返回 (提取结果, 原始会话信息)。
    """
    prompt = agent_registry.build_agent_prompt(agent_id, payload)
    if prompt is None:
        return None, None
    s = get_settings()
    _push_activity(task_id, agent_id, "agent_start",
                   model=s.dsh_model, provider=s.dsh_provider,
                   preview=prompt[:200])
    result = dsh_manager.run_turn(prompt, session_id=f"{task_id}--{agent_id}",
                                  on_event=_activity_handler(task_id, agent_id))
    if result.get("status") != "ok":
        _push_activity(task_id, agent_id, "agent_end", ok=False,
                       summary=str(result.get("message", "执行失败"))[:300])
        return None, result
    entities.save_agent_session(task_id, agent_id, result.get("session_id", ""), "ok", 1)
    extracted = _extract_json(result.get("final_response", ""))
    _push_activity(task_id, agent_id, "agent_end", ok=True,
                   preview=(result.get("final_response") or "")[:800])
    return extracted, result


def _agent_done(task_id: str, agent_id: str, ok: bool, summary: str) -> None:
    """阶段结论（含数量统计）追加到 Agent 卡片尾部。"""
    _push_activity(task_id, agent_id, "result", ok=ok, summary=summary[:400])


def _requirement_digest(items: list[dict[str, Any]], limit: int = 12) -> str:
    """需求条目紧凑摘要（供下游 Agent 消费，控制 token）。"""
    lines = []
    for it in items[:limit]:
        ac = "；".join(it.get("acceptance_criteria", [])[:3])
        lines.append(f"- {it['id']} [{it.get('priority', 'P1')}] {it['title']}：{it.get('description', '')[:150]}"
                     + (f"（验收：{ac[:200]}）" if ac else ""))
    return "\n".join(lines)


def _evidence_digest(evidence: list[dict[str, Any]], limit: int = 15) -> str:
    lines = []
    for ev in evidence[:limit]:
        lines.append(f"- {ev.get('project', '?')} {ev.get('path', '?')}:{ev.get('line', '?')} "
                     f"{ev.get('symbol', '')}（置信 {ev.get('confidence', '?')}）")
    return "\n".join(lines)


def _rule_fallback_requirements(report) -> list[dict[str, Any]]:
    return [
        {"id": r.id, "title": r.title, "description": r.description,
         "priority": r.priority.value, "acceptance_criteria": r.acceptance_criteria}
        for r in report.requirements
    ]


def _run_task(task_id: str, mode: str = "full") -> None:
    s = get_settings()
    task = entities.get_task(task_id)
    if task is None:
        return
    entities.update_task(task_id, status="running")
    _emit(task_id, "received", 5, "已接收需求，开始分析", status="running")
    degraded: list[str] = []

    try:
        # ── 阶段 0：规则分析（离线保底，产出报告与基础需求条目）──────────────
        _emit(task_id, "rule-analysis", 15, "正在执行规则分析（接口定位/证据扫描）")
        workspace = task["workspace"] or str(s.workspace)
        branch = task["branch"] or s.branch
        projects = (task["projects"] or "").split()
        report = _run_rule_analysis(task, workspace, branch, projects)
        outputs = write_reports(report, s.report_dir)
        entities.save_report(task_id, report.report_id, outputs, {"requirements": len(report.requirements)})
        entities.update_task(task_id, report_id=report.report_id)
        _emit(task_id, "rule-analysis", 20, f"规则分析完成，报告 {report.report_id}")

        source_text = task["source_text"] or ""

        # ── 阶段 1：需求结构化（requirement-analyst）────────────────────────
        _emit(task_id, "requirement-analyst", 28, "Agent[需求分析] 正在解析需求条目")
        items, session = _run_agent(task_id, "requirement-analyst", source_text[:6000])
        dsh_mode = items is not None
        if not dsh_mode:
            items = _rule_fallback_requirements(report)
            degraded.append("requirement-analyst")
            _emit(task_id, "requirement-analyst", 32, f"DSH 未启用/解析失败，规则解析 {len(items)} 条需求")
            _agent_done(task_id, "requirement-analyst", False, f"DSH 未参与，规则解析 {len(items)} 条需求")
        else:
            _emit(task_id, "requirement-analyst", 32, f"Agent[需求分析] 输出 {len(items)} 条结构化需求")
            _agent_done(task_id, "requirement-analyst", True, f"输出 {len(items)} 条结构化需求（含优先级与验收标准）")
        entities.save_requirements(task_id, items)

        if not items:
            _emit(task_id, "completed", 100, "分析完成：未解析出需求条目", status="completed")
            entities.update_task(task_id, status="completed")
            return

        # ── DSH 可用：继续 2-8 阶段语义分析 ────────────────────────────────
        if dsh_mode:
            req_digest = _requirement_digest(items)

            # 阶段 2：项目相关性（project-scout）
            _emit(task_id, "project-scout", 38, "Agent[项目侦察] 正在判断项目相关性")
            relevant_projects, _ = _run_agent(
                task_id, "project-scout",
                f"项目清单：{', '.join(projects) if projects else '（未指定，workspace 下自行判断）'}\n"
                f"工作区：{workspace}\n\n需求条目：\n{req_digest}")
            if relevant_projects is None:
                degraded.append("project-scout")
                _emit(task_id, "project-scout", 42, "项目相关性判断失败，按全部项目继续")
                _agent_done(task_id, "project-scout", False, "项目相关性判断失败，按全部项目继续")
            else:
                names = [str(p.get("name")) for p in relevant_projects if isinstance(p, dict) and p.get("relevant")]
                if names:
                    projects = names[:5]
                _emit(task_id, "project-scout", 42, f"Agent[项目侦察] 相关项目：{', '.join(names or projects)}")
                _agent_done(task_id, "project-scout", True, f"相关项目：{', '.join(names or projects)}")

            # 阶段 3：代码证据（code-locator，可实查源码）
            _emit(task_id, "code-locator", 50, "Agent[代码定位] 正在检索源码定位证据")
            evidence, _ = _run_agent(
                task_id, "code-locator",
                f"你可以使用 glob/grep/read 工具在源码工作区实际检索。\n"
                f"工作区：{workspace}（项目：{', '.join(projects) if projects else '自行探索'}）\n\n"
                f"需求条目：\n{req_digest}\n\n"
                "请实际检索源码，输出 JSON：evidence[{{project,path,line,symbol,snippet,confidence(0-1)}}]。")
            if isinstance(evidence, list) and evidence:
                n = entities.save_code_evidence(task_id, evidence)
                _emit(task_id, "code-locator", 56, f"Agent[代码定位] 定位 {n} 处代码证据")
                _agent_done(task_id, "code-locator", True,
                            f"实查源码定位 {n} 处代码证据（含文件路径/行号/符号）")
            else:
                degraded.append("code-locator")
                _emit(task_id, "code-locator", 56, "代码证据定位失败/无结果，跳过该阶段")
                _agent_done(task_id, "code-locator", False, "代码证据定位失败/无结果")

            # 阶段 4：调用链（call-chain）
            _emit(task_id, "call-chain", 62, "Agent[调用链] 正在分析跨项目调用链")
            chains, _ = _run_agent(
                task_id, "call-chain",
                f"项目：{', '.join(projects)}\n\n需求条目：\n{req_digest}\n\n"
                "输出 JSON：chains[{{name,risk(high|medium|low),steps[{{project,component,call}}]}}]。")
            if isinstance(chains, list) and chains:
                n = entities.save_impact_scopes(task_id, chains)
                _emit(task_id, "call-chain", 66, f"Agent[调用链] 识别 {n} 条影响链路")
                _agent_done(task_id, "call-chain", True, f"识别 {n} 条跨项目影响链路")
            else:
                degraded.append("call-chain")
                _emit(task_id, "call-chain", 66, "调用链分析失败/无结果，跳过该阶段")
                _agent_done(task_id, "call-chain", False, "调用链分析失败/无结果")

            # 阶段 5：实现审查（impl-reviewer，暂存内存待合并）
            _emit(task_id, "impl-reviewer", 72, "Agent[实现审查] 正在逐条对比需求与实现")
            ev_digest = _evidence_digest(entities.list_code_evidence(task_id))
            impl_result, _ = _run_agent(
                task_id, "impl-reviewer",
                f"需求条目：\n{req_digest}\n\n代码证据：\n{ev_digest or '（无代码证据）'}\n\n"
                "输出 JSON：assessments[{{requirement_id,status(implemented|partially_implemented|not_found|uncertain),"
                "verdict(pass|fail|blocked|needs_review),confidence,evidence_refs[],gaps[]}}]。")
            if not isinstance(impl_result, list):
                impl_result = None
                degraded.append("impl-reviewer")
                _emit(task_id, "impl-reviewer", 76, "实现审查失败，跳过该阶段")
                _agent_done(task_id, "impl-reviewer", False, "实现审查失败，跳过该阶段")
            else:
                _emit(task_id, "impl-reviewer", 76, f"Agent[实现审查] 完成 {len(impl_result)} 条审查结论")
                _agent_done(task_id, "impl-reviewer", True, f"完成 {len(impl_result)} 条逐项实现审查结论")

            # 分析模式：只跑需求结构化 + 代码定位 + 实现审查，不生成用例/报告
            if mode == "analyze":
                _emit(task_id, "completed", 100,
                      f"分析完成（仅分析）：{len(items or [])} 条需求 / {len(entities.list_code_evidence(task_id))} 处证据",
                      status="completed")
                entities.update_task(task_id, status="completed")
                return

            # 阶段 6：测试用例（test-designer）
            _emit(task_id, "test-designer", 82, "Agent[测试设计] 正在生成五类测试用例")
            cases, _ = _run_agent(
                task_id, "test-designer",
                f"需求条目：\n{req_digest}\n\n"
                "输出 JSON：cases[{{requirement_id,title,kind(functional|negative|boundary|idempotency|security),"
                "preconditions[],steps[],expected}}]。")
            if isinstance(cases, list) and cases:
                n = entities.save_test_cases(task_id, cases)
                _emit(task_id, "test-designer", 86, f"Agent[测试设计] 生成 {n} 条测试用例")
                _agent_done(task_id, "test-designer", True, f"生成 {n} 条五类测试用例")
            else:
                degraded.append("test-designer")
                _emit(task_id, "test-designer", 86, "测试用例生成失败/无结果，跳过该阶段")
                _agent_done(task_id, "test-designer", False, "测试用例生成失败/无结果")

            # 阶段 7：质量裁决（quality-judge，与 impl-reviewer 合并入库）
            _emit(task_id, "quality-judge", 90, "Agent[质量裁决] 正在评估风险与上线建议")
            verdicts, _ = _run_agent(
                task_id, "quality-judge",
                f"需求条目：\n{req_digest}\n\n实现审查：\n{json.dumps(impl_result, ensure_ascii=False)[:2000] if impl_result else '（无）'}\n\n"
                "输出 JSON：verdicts[{{requirement_id,risk(high|medium|low),rationale,recommendation}}]。")
            merged = _merge_assessments(items, impl_result, verdicts)
            if merged:
                entities.save_assessments(task_id, merged)
                high = sum(1 for a in merged if a.get("risk") == "high")
                review = sum(1 for a in merged if a.get("verdict") in ("needs_review", "blocked"))
                _emit(task_id, "quality-judge", 93,
                      f"Agent[质量裁决] {len(merged)} 条结论（高风险 {high}，待复核 {review}）")
                _agent_done(task_id, "quality-judge", True,
                            f"{len(merged)} 条裁决结论（高风险 {high}，待复核 {review}）")
            else:
                degraded.append("quality-judge")
                _emit(task_id, "quality-judge", 93, "质量裁决失败，跳过该阶段")
                _agent_done(task_id, "quality-judge", False, "质量裁决失败，跳过该阶段")

            # 阶段 8：报告摘要（report-writer）
            _emit(task_id, "report-writer", 96, "Agent[报告] 正在生成三视角摘要")
            views_raw, _ = _run_agent(
                task_id, "report-writer",
                f"需求条目：\n{req_digest}\n\n"
                f"实现审查：{json.dumps(impl_result, ensure_ascii=False)[:1500] if impl_result else '无'}\n\n"
                f"测试用例数：{len(entities.list_test_cases(task_id))}\n\n"
                "输出 JSON：views{{dev,qa,product}}，每项是面向该角色的中文结论摘要。")
            # 模型可能输出 {"views":{...}} 或裸 {"dev","qa","product"}，两种都兼容
            if isinstance(views_raw, dict) and isinstance(views_raw.get("views"), dict):
                views = views_raw["views"]
            else:
                views = views_raw
            if isinstance(views, dict) and any(views.get(k) for k in ("dev", "qa", "product")):
                entities.save_report_views(task_id, views)
                _emit(task_id, "report-writer", 98, "Agent[报告] 三视角摘要完成")
                _agent_done(task_id, "report-writer", True, "研发/测试/产品三视角摘要完成")
            else:
                degraded.append("report-writer")
                _emit(task_id, "report-writer", 98, "报告摘要失败，跳过该阶段")
                _agent_done(task_id, "report-writer", False, "报告摘要失败，跳过该阶段")

        # ── 收尾 ─────────────────────────────────────────────────────────────
        parts = [f"{len(items)} 条需求",
                 f"{len(entities.list_code_evidence(task_id))} 处证据",
                 f"{len(entities.list_test_cases(task_id))} 条用例",
                 f"报告 {report.report_id}"]
        if degraded:
            parts.append(f"降级阶段 {len(degraded)}：{'/'.join(degraded)}")
        _emit(task_id, "completed", 100, "分析完成：" + "，".join(parts), status="completed")
        entities.update_task(task_id, status="completed")
    except Exception as exc:  # 任务级兜底：失败入库，不崩服务
        entities.update_task(task_id, status="failed", error=str(exc)[:2000])
        _emit(task_id, "failed", 100, f"分析失败：{exc}", status="failed", error=str(exc))


def _merge_assessments(items: list[dict], impl_result: list | None, verdicts: list | None) -> list[dict]:
    """impl-reviewer 结论与 quality-judge 裁决按 requirement_id 合并。"""
    risk_map: dict[str, dict] = {}
    if isinstance(verdicts, list):
        for v in verdicts:
            if isinstance(v, dict) and v.get("requirement_id"):
                risk_map[str(v["requirement_id"])] = v
    merged: list[dict] = []
    if isinstance(impl_result, list) and impl_result:
        for a in impl_result:
            if not isinstance(a, dict):
                continue
            rid = str(a.get("requirement_id", ""))
            v = risk_map.get(rid, {})
            merged.append({
                "requirement_id": rid,
                "verdict": a.get("verdict", ""),
                "risk": v.get("risk", ""),
                "confidence": a.get("confidence"),
                "evidence_refs": a.get("evidence_refs", []),
                "gaps": a.get("gaps", []) or ([v.get("rationale")] if v.get("rationale") else []),
            })
    elif risk_map:  # 只有裁决没有审查
        for rid, v in risk_map.items():
            merged.append({"requirement_id": rid, "verdict": "", "risk": v.get("risk", ""),
                           "confidence": None, "evidence_refs": [], "gaps": [v.get("rationale", "")]})
    return merged


def _run_rule_analysis(task: dict[str, Any], workspace: str, branch: str, projects: list[str]):
    text = task["source_text"] or task["title"]
    with NamedTemporaryFile(delete=False, suffix=".md", mode="w", encoding="utf-8") as temp:
        temp.write(text)
        path = Path(temp.name)
    try:
        return NavigatorAnalyzer(Path(workspace)).analyze(path, projects, branch)
    finally:
        path.unlink(missing_ok=True)
