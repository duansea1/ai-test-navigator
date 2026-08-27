"""需求分析域：分析任务流（入库 + 异步执行 + SSE 进度）+ 需求池查询。

M1 新端点（前端主链路）：
  POST /api/requirements/tasks                     创建分析任务（异步执行）
  GET  /api/requirements/tasks                     任务列表
  GET  /api/requirements/tasks/{id}                任务详情
  GET  /api/requirements/tasks/{id}/events         SSE 进度流
  GET  /api/requirements/tasks/{id}/requirements   需求条目（结构化结果）

MVP 兼容端点（旧页面）：/api/analyze、/api/analyze/stream
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.db import entities
from app.services import orchestrator
from app.services.analyzer import NavigatorAnalyzer
from app.services.reporter import write_reports

router = APIRouter(tags=["requirements"])

_TEXT_SUFFIXES = {".md", ".txt", ".csv", ".json", ".xml", ".yaml", ".yml", ".log"}


@router.post("/requirements/tasks")
async def create_task(
    text: str = Form(""),
    requirement: UploadFile | None = File(None),
    attachments: list[UploadFile] = File(default=[]),
    projects: str = Form(""),
    branch: str = Form(""),
    workspace: str = Form(""),
    title: str = Form(""),
    mode: str = Form("auto"),
    conversation_id: str = Form(""),
) -> dict[str, object]:
    s = get_settings()
    projects = projects or ""
    branch = branch or s.branch
    workspace = workspace or str(s.workspace)
    sources: list[str] = []
    if text.strip():
        sources.append(text.strip())
    if requirement is not None:
        sources.append((await requirement.read()).decode("utf-8", errors="ignore"))
    for item in attachments:
        data = await item.read()
        suffix = Path(item.filename or "attachment.bin").suffix.lower()
        if suffix in _TEXT_SUFFIXES:
            sources.append(data.decode("utf-8", errors="ignore"))
    if not sources:
        raise HTTPException(400, "请输入需求文字，或上传需求文档/文本附件")
    source_text = "\n\n".join(sources)
    task_title = title.strip() or (sources[0].strip().splitlines()[0][:80] if sources[0].strip() else "未命名分析任务")
    task_id = orchestrator.create_task(task_title, source_text, projects, branch, workspace, mode=mode)
    # 多轮会话：任务消息入会话流（user 消息在 /chat 已记；这里补 assistant 任务块）
    conv_id = conversation_id.strip()
    if conv_id:
        try:
            from app.db import entities as E
            if E.get_conversation(conv_id):
                E.save_message(conv_id, "assistant", f"已创建分析任务「{task_title}」，8-Agent 流水线执行中。",
                               intent=mode if mode != "auto" else "full", task_id=task_id)
                E.touch_conversation(conv_id)
        except Exception:  # 会话落库失败不阻塞任务创建
            pass
    return {"task_id": task_id, "conversation_id": conv_id or None,
            "status": "pending", "message": "任务已创建，正在异步执行"}


@router.post("/requirements/classify")
async def classify(text: str = Form(""), conversation_id: str = Form("")) -> dict[str, object]:
    """意图识别：用 DSH 判断输入属于 问答/需求分析/全流程（最优解），失败回退启发式。
    conversation_id 关联多轮会话（同会话共享 DSH 上下文）。"""
    from app.services.router import classify as do_classify
    return await asyncio.to_thread(do_classify, text or "", conversation_id or None)


@router.post("/chat")
async def chat(text: str = Form(""), conversation_id: str = Form(""),
               mode: str = Form("")) -> dict[str, object]:
    """对话回合（多轮）：classify（qa 时直接回答）+ 消息落库。
    analyze/full 由前端转 /requirements/tasks 建任务，这里只处理问答回合。
    mode 显式指定时跳过 classify（用户手动选的模式）。"""
    from app.db import entities as E
    from app.services.router import classify as do_classify, qa_answer

    t = (text or "").strip()
    conv_id = conversation_id.strip() or None

    def _run() -> dict[str, object]:
        # 无会话时自动开一个（首次对话）
        if conv_id is None:
            cid = E.create_conversation(t[:80] or "新会话")
        else:
            cid = conv_id
            if not E.get_conversation(cid):
                raise HTTPException(404, f"会话不存在：{cid}")
        E.save_message(cid, "user", t)
        if mode and mode != "auto" and mode != "qa":
            intent = {"intent": mode, "confidence": 1.0, "reason": "用户手动指定模式"}
        else:
            intent = do_classify(t, cid)
        if intent["intent"] == "qa" or mode == "qa":
            answer = qa_answer(t, cid)
            E.save_message(cid, "assistant", answer, intent=intent["intent"])
            E.touch_conversation(cid)
            return {"conversation_id": cid, "intent": "qa", "reason": intent.get("reason", ""),
                    "answer": answer, "task_id": None}
        # analyze/full：记一条意图，任务由 /requirements/tasks 创建后由前端补记
        E.touch_conversation(cid)
        return {"conversation_id": cid, "intent": intent["intent"],
                "reason": intent.get("reason", ""), "answer": None, "task_id": None}

    return await asyncio.to_thread(_run)


@router.get("/conversations")
async def list_conversations(limit: int = 50) -> dict[str, object]:
    """会话列表（最近活跃在前）。"""
    from app.db import entities as E
    return {"conversations": E.list_conversations(limit=limit)}


@router.get("/conversations/{conv_id}/messages")
async def conversation_messages(conv_id: str) -> dict[str, object]:
    """会话消息流（正序）：user / assistant（含 intent 与关联 task_id）。"""
    from app.db import entities as E
    if E.get_conversation(conv_id) is None:
        raise HTTPException(404, f"会话不存在：{conv_id}")
    return {"conversation_id": conv_id, "messages": E.list_messages(conv_id)}


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str) -> dict[str, object]:
    """删除会话：连带删 chat_messages + 会话内全部任务及其衍生数据。

    会话内挂的任务被全删（任务悬空没人能打开没意义）；任务的七张衍生表跟着级联。
    删当前打开的会话时前端应切回新会话视图。"""
    from app.db import entities as E
    res = E.delete_conversation(conv_id)
    if not res["existed"]:
        raise HTTPException(404, f"会话不存在：{conv_id}")
    return {"conversation_id": conv_id, "deleted": True,
            "deleted_tasks": res["deleted_tasks"]}


@router.get("/requirements/tasks")
async def list_tasks(limit: int = 50, status: str = "") -> dict[str, object]:
    return {"tasks": entities.list_tasks(limit=limit, status=status)}


@router.get("/requirements/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, object]:
    task = entities.get_task(task_id)
    if task is None:
        raise HTTPException(404, f"任务不存在：{task_id}")
    return task


@router.get("/requirements/tasks/{task_id}/events")
async def task_events(task_id: str):
    """SSE 进度流：按内存版本号增量推送，任务终态后关闭。"""
    if entities.get_task(task_id) is None:
        raise HTTPException(404, f"任务不存在：{task_id}")

    async def stream():
        last_version = 0
        idle = 0
        while True:
            snap = orchestrator.snapshot(task_id)
            version = snap.get("version", 0)
            if version > last_version:
                last_version = version
                idle = 0
                yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
                if snap.get("status") in ("completed", "failed"):
                    return
            else:
                idle += 1
            await asyncio.sleep(0.4 if idle < 5 else 1.0)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/requirements/tasks/{task_id}/activity")
async def task_activity(task_id: str):
    """SSE 聊天活动流：先回放全部历史，再增量推送新事件；任务终态后关闭。

    事件结构（items 数组，每项含 seq/time/agent/agent_name/kind）：
      agent_start  Agent 开始（含 model/provider/preview）
      tool         工具调用（tool + detail 参数预览）
      text         模型文本输出增量
      agent_end    Agent 回合结束（ok + preview 原始输出）
      result       阶段结论摘要（ok + summary）
      stage        系统阶段消息（received/rule-analysis/completed/failed）
    """
    if entities.get_task(task_id) is None:
        raise HTTPException(404, f"任务不存在：{task_id}")

    async def stream():
        last_seq = 0
        idle = 0
        while True:
            items = orchestrator.activity_items(task_id)
            new = [it for it in items if it.get("seq", 0) > last_seq]
            terminal = False
            if new:
                last_seq = new[-1].get("seq", last_seq)
                idle = 0
                # 终态判定：收到 completed/failed 系统消息即收尾
                if any(it.get("stage") in ("completed", "failed") for it in new):
                    terminal = True
            else:
                idle += 1
                if idle > 3:  # 静默期查任务状态，防终态事件丢失导致挂起
                    task = entities.get_task(task_id)
                    if task and task["status"] in ("completed", "failed"):
                        terminal = True
            if new or terminal:
                yield f"data: {json.dumps({'items': new}, ensure_ascii=False)}\n\n"
            if terminal:
                return
            await asyncio.sleep(0.4 if idle < 5 else 1.0)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/requirements/tasks/{task_id}/requirements")
async def task_requirements(task_id: str) -> dict[str, object]:
    if entities.get_task(task_id) is None:
        raise HTTPException(404, f"任务不存在：{task_id}")
    return {"task_id": task_id, "items": entities.list_requirements(task_id)}


@router.get("/requirements/tasks/{task_id}/analysis")
async def task_analysis(task_id: str) -> dict[str, object]:
    """任务全景结果：需求/代码证据/影响范围/测试用例/裁决结论/三视角摘要/Agent 会话。"""
    task = entities.get_task(task_id)
    if task is None:
        raise HTTPException(404, f"任务不存在：{task_id}")
    return {
        "task": task,
        "requirements": entities.list_requirements(task_id),
        "evidence": entities.list_code_evidence(task_id),
        "impacts": entities.list_impact_scopes(task_id),
        "test_cases": entities.list_test_cases(task_id),
        "assessments": entities.list_assessments(task_id),
        "views": entities.list_report_views(task_id),
        "agent_sessions": entities.list_agent_sessions(task_id),
    }


# ─── MVP 兼容端点（旧页面，逐步下线）────────────────────────────────────────

@router.post("/analyze")
async def analyze(
    requirement: UploadFile | None = File(None),
    text: str = Form(""),
    attachments: list[UploadFile] = File(default=[]),
    projects: str = Form(...),
    workspace: str = Form(""),
    branch: str = Form(""),
) -> dict[str, object]:
    s = get_settings()
    workspace = workspace or str(s.workspace)
    branch = branch or s.branch
    sources: list[str] = []
    if text.strip():
        sources.append(text.strip())
    if requirement is not None:
        sources.append((await requirement.read()).decode("utf-8", errors="ignore"))
    attachment_notes: list[str] = []
    for item in attachments:
        data = await item.read()
        suffix = Path(item.filename or "attachment.bin").suffix.lower()
        attachment_notes.append(f"{item.filename or 'attachment'} ({len(data)} bytes, {suffix or 'unknown type'})")
        if suffix in _TEXT_SUFFIXES:
            sources.append(data.decode("utf-8", errors="ignore"))
    if not sources:
        return {"status": "needs_review", "message": "请直接输入需求文字，或上传需求文档/图片/附件。", "attachments": attachment_notes}
    with NamedTemporaryFile(delete=False, suffix=".md", mode="w", encoding="utf-8") as temp:
        temp.write("\n\n".join(sources))
        requirement_path = Path(temp.name)
    try:
        report = NavigatorAnalyzer(Path(workspace)).analyze(requirement_path, projects.split(), branch)
        report.notes.extend([f"收到附件：{note}" for note in attachment_notes])
        outputs = write_reports(report, s.report_dir)
        return {"report_id": report.report_id, "summary": report.summary, "outputs": outputs, "attachments": attachment_notes}
    finally:
        requirement_path.unlink(missing_ok=True)


@router.get("/analyze/stream")
async def analyze_stream(text: str, projects: str, workspace: str = "", branch: str = ""):
    s = get_settings()
    workspace = workspace or str(s.workspace)
    branch = branch or s.branch

    async def events():
        yield f"data: {json.dumps({'stage': 'received', 'message': '已接收接口审查请求'}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(0.05)
        yield f"data: {json.dumps({'stage': 'locating', 'message': '正在精确定位接口入口和业务实现'}, ensure_ascii=False)}\n\n"
        with NamedTemporaryFile(delete=False, suffix=".md", mode="w", encoding="utf-8") as temp:
            temp.write(text)
            path = Path(temp.name)
        try:
            report = NavigatorAnalyzer(Path(workspace)).analyze(path, projects.split(), branch)
            outputs = write_reports(report, s.report_dir)
            yield f"data: {json.dumps({'stage': 'completed', 'report_id': report.report_id, 'summary': report.summary, 'outputs': outputs}, ensure_ascii=False)}\n\n"
        finally:
            path.unlink(missing_ok=True)

    return StreamingResponse(events(), media_type="text/event-stream")
