# -*- coding: utf-8 -*-
"""live 冒烟：POST /api/chat/stream 五场景（纯文本/带项目/附件-only/多轮/图片转任务）。
SSE 用 urllib 逐行读（无 requests 依赖）。"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8090"
BOUNDARY = "----livesmoke9876543210"


def post_sse(path: str, fields: dict, files: list | None = None, timeout: int = 120):
    """multipart POST + 解析 SSE data: 行，返回事件列表。"""
    body = b""
    for k, v in fields.items():
        body += (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode("utf-8")
    for name, filename, content, ctype in (files or []):
        body += (f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                 f"filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n").encode("utf-8")
        body += content + b"\r\n"
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


def main() -> int:
    fails = []

    # ── 场景 1：纯文本问答流式 ──────────────────────────────────────────
    evs = post_sse("/api/chat/stream", {"text": "你好，请用一句话介绍你能做什么？"})
    deltas = [e["delta"] for e in evs if "delta" in e]
    done = [e for e in evs if e.get("done")]
    print(f"[1] 纯文本问答：{len(evs)} 事件，{len(deltas)} delta，done={bool(done)}")
    if not deltas:
        fails.append("场景1 无 delta——流式未生效")
    if not done or not (done[0].get("answer") or "").strip():
        fails.append("场景1 终帧无 answer")
    if not done or done[0].get("intent") != "qa":
        fails.append(f"场景1 intent 应为 qa，got {done[0].get('intent') if done else 'None'}")
    conv_id = done[0]["conversation_id"] if done else ""
    print(f"    conv={conv_id[:20]} answer={(done[0].get('answer') or '')[:50]!r}")

    # ── 场景 2：文本 + 项目 ────────────────────────────────────────────
    evs2 = post_sse("/api/chat/stream",
                    {"text": "这个项目的登录逻辑该怎么测？", "projects": "baofu-customer-core"})
    done2 = [e for e in evs2 if e.get("done")]
    ans2 = done2[0].get("answer", "") if done2 else ""
    print(f"[2] 文本+项目：done={bool(done2)} answer={ans2[:60]!r}")
    if not done2 or not ans2:
        fails.append("场景2 带 projects 问答无 answer")

    # ── 场景 3：附件-only（文本附件） ──────────────────────────────────
    doc = "需求：手机号+验证码登录，连续输错5次锁定60分钟。".encode("utf-8")
    evs3 = post_sse("/api/chat/stream", {"text": ""},
                    files=[("attachments", "login-req.md", doc, "text/markdown")])
    done3 = [e for e in evs3 if e.get("done")]
    print(f"[3] 附件-only：{len(evs3)} 事件 done={bool(done3)}")
    if not done3:
        fails.append("场景3 附件-only 无终帧")
    elif not (done3[0].get("answer") or "").strip() and done3[0].get("intent") != "analyze":
        fails.append("场景3 附件-only 既无 answer 也非 analyze")

    # ── 场景 4：多轮追问（复用 conv_id） ───────────────────────────────
    evs4 = post_sse("/api/chat/stream", {"text": "接着上面的话题，再展开讲一点？",
                                         "conversation_id": conv_id})
    deltas4 = [e["delta"] for e in evs4 if "delta" in e]
    done4 = [e for e in evs4 if e.get("done")]
    print(f"[4] 多轮追问：{len(deltas4)} delta done={bool(done4)}")
    if not done4:
        fails.append("场景4 追问无终帧")
    elif done4[0].get("conversation_id") != conv_id:
        fails.append("场景4 追问未复用会话")
    elif not (done4[0].get("answer") or "").strip():
        fails.append("场景4 追问无 answer")

    # ── 场景 5：图片附件 → 终帧 intent=analyze（前端转建任务） ───────────
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # 伪 PNG（后端按后缀判断）
    evs5 = post_sse("/api/chat/stream", {"text": "分析这张图"},
                    files=[("attachments", "shot.png", png, "image/png")])
    done5 = [e for e in evs5 if e.get("done")]
    intent5 = done5[0].get("intent") if done5 else None
    print(f"[5] 图片+文本：done={bool(done5)} intent={intent5}")
    if not done5:
        fails.append("场景5 图片附件无终帧")
    elif intent5 not in ("qa", "analyze"):
        fails.append(f"场景5 intent 异常：{intent5}")

    # ── 场景 6：纯图片（无文字）→ intent=analyze 引导建任务 ─────────────
    evs6 = post_sse("/api/chat/stream", {"text": ""},
                    files=[("attachments", "shot.png", png, "image/png")])
    done6 = [e for e in evs6 if e.get("done")]
    intent6 = done6[0].get("intent") if done6 else None
    print(f"[6] 纯图片（无文字）：done={bool(done6)} intent={intent6}")
    if intent6 != "analyze":
        fails.append(f"场景6 纯图片应 intent=analyze，got {intent6}")

    # ── 场景 7：文本附件经 stream 端点并入提问（输入保真回归） ──────────
    evs7 = post_sse("/api/chat/stream", {"text": "这个文档里的规则，一句话概括"},
                    files=[("attachments", "rule.md",
                            "规则：连续输错5次锁定60分钟。".encode("utf-8"), "text/markdown")])
    done7 = [e for e in evs7 if e.get("done")]
    ans7 = done7[0].get("answer", "") if done7 else ""
    hit7 = ("5" in ans7 or "五" in ans7) and ("60" in ans7 or "六十" in ans7)
    print(f"[7] 文本附件经 stream：done={bool(done7)} 命中附件内容={hit7}")
    if not done7:
        fails.append("场景7 文本附件 stream 无终帧")
    elif not hit7:
        fails.append(f"场景7 回答未体现附件内容（附件可能被丢）：{ans7[:80]!r}")

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
