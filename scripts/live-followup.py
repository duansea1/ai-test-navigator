# -*- coding: utf-8 -*-
"""live 冒烟（轻量）：已完成任务的会话里追问结论——验证回写 + 历史注入链路。"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8090"
BOUNDARY = "----livefollow990011"


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


def main() -> int:
    conv_id = sys.argv[1] if len(sys.argv) > 1 else "conv-8a0da0bd9249"
    evs = post_sse("/api/chat/stream", {
        "text": "刚才那个分析任务结论如何？一句话概括", "conversation_id": conv_id})
    done = [e for e in evs if e.get("done")]
    intent = done[0].get("intent") if done else None
    ans = (done[0].get("answer") or "") if done else ""
    print(f"意图：{intent}")
    print(f"回答：{ans[:200]}")
    ok = intent == "qa" and any(k in ans for k in ("条需求", "处证据", "锁定", "验证码", "登录", "完成"))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
