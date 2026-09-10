# -*- coding: utf-8 -*-
"""live 冒烟：输入→建任务→8-Agent→结论回写会话→追问闭环（输出侧记忆验证）。

链路：chat/stream（意图=analyze，自动建会话）→ /requirements/tasks（建任务）
→ 轮询任务终态 → 查会话消息流应含「分析任务完成」回写 → 同会话追问
「刚才那个任务结论如何」→ 回答应引用任务统计（证明历史注入生效）。
"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8090"
BOUNDARY = "----livetask9977553110"


def post_form(path: str, fields: dict, timeout: int = 60) -> dict:
    body = b""
    for k, v in fields.items():
        body += (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode("utf-8")
    body += f"--{BOUNDARY}--\r\n".encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def post_sse(path: str, fields: dict, timeout: int = 180):
    body = b""
    for k, v in fields.items():
        body += (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode("utf-8")
    body += f"--{BOUNDARY}--\r\n".encode("utf-8")
    req = urllib.request.Request(BASE + path, data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={BOUNDARY}"})
    events = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def get(path: str, timeout: int = 15):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    fails = []
    req_text = "分析一个登录需求：手机号+验证码登录，连续输错5次锁定60分钟，锁定期间拒绝登录请求"

    # ① 流式意图识别 → analyze（拿到 conversation_id）
    evs = post_sse("/api/chat/stream", {"text": req_text, "mode": "analyze"})
    done = [e for e in evs if e.get("done")]
    conv_id = done[0].get("conversation_id") if done else None
    intent = done[0].get("intent") if done else None
    print(f"[1] 意图：{intent}，会话 {conv_id}")
    if not conv_id or intent not in ("analyze", "full"):
        fails.append(f"步骤1 意图/会话异常：intent={intent} conv={conv_id}")

    # ② 建任务（挂会话）
    task = post_form("/api/requirements/tasks", {
        "text": req_text, "mode": "analyze", "conversation_id": conv_id or ""})
    tid = task.get("task_id")
    print(f"[2] 任务 {tid} 已创建，轮询执行…")
    if not tid:
        fails.append("步骤2 任务创建失败")
        print("FAIL:", fails)
        return 1

    # ③ 轮询到终态（analyze 模式，最长 8 分钟）
    status = "pending"
    for _ in range(240):
        time.sleep(2)
        t = get(f"/api/requirements/tasks/{tid}")
        status = t["status"]
        if status in ("completed", "failed"):
            break
    print(f"[3] 任务终态：{status}（{(t.get('message') or '')[:60]}）")
    if status != "completed":
        fails.append(f"任务未完成：{status} {(t.get('error') or '')[:100]}")

    # ④ 会话消息流应含「分析任务完成」回写（带 task_id）
    msgs = get(f"/api/conversations/{conv_id}/messages")["messages"]
    back = [m for m in msgs if m.get("task_id") == tid and "分析任务完成" in str(m.get("content"))]
    print(f"[4] 结论回写：{'找到' if back else '缺失'}（会话共 {len(msgs)} 条消息）")
    if not back:
        fails.append("步骤4 任务结论未回写会话")
    else:
        print(f"    回写内容：{back[0]['content'][:80]}")

    # ⑤ 同会话追问——回答应引用任务统计（历史注入生效的证明）
    evs5 = post_sse("/api/chat/stream", {
        "text": "刚才那个分析任务结论如何？一句话概括", "conversation_id": conv_id})
    done5 = [e for e in evs5 if e.get("done")]
    ans5 = (done5[0].get("answer") or "") if done5 else ""
    print(f"[5] 追问回答：{ans5[:100]}")
    # 判据：回答里出现「条」计数或需求/证据/锁定等任务关键词（而非茫然反问）
    hit = any(k in ans5 for k in ("条需求", "处证据", "锁定", "验证码", "登录", "完成"))
    if not hit:
        fails.append(f"追问回答未引用任务结论：{ans5[:80]!r}")

    print()
    if fails:
        print("FAIL ×%d" % len(fails))
        for f in fails:
            print(" -", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
