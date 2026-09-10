# -*- coding: utf-8 -*-
"""诊断：直接调 dsh_manager.run_turn，抓全部事件——搞清「模型未返回内容」的真相。

用法：python -X utf8 scripts/debug-dsh-turn.py [session_id] [prompt]
默认：全新 session（router-debug--probe），prompt 为 intent-classifier 试探。
输出：每个事件的 type / finish_reason / 最后一条 assistant 消息的 content 块结构。
"""
import sys

sys.path.insert(0, r"C:\Akua\ai-test-navigator\backend")

from app.dsh.runtime import manager  # noqa: E402
from app.dsh import agents as agent_registry  # noqa: E402


def main() -> int:
    session_id = sys.argv[1] if len(sys.argv) > 1 else f"router-debug--probe-{__import__('time').strftime('%H%M%S')}"
    if len(sys.argv) > 2:
        prompt = sys.argv[2]
    else:
        prompt = (agent_registry.get_agent("intent-classifier").system_prompt
                  + "\n\n用户输入：hello")

    events = []
    res = manager.run_turn(prompt, session_id=session_id,
                           on_event=lambda e: events.append(e))
    print("status:", res.get("status"))
    print("finish_reason:", res.get("finish_reason"))
    print("final_response len:", len(res.get("final_response") or ""))
    print("final_response[:300]:", (res.get("final_response") or "")[:300])
    print("event_count:", len(events), "res.event_count:", res.get("event_count"))
    print("last_error:", manager.last_error)
    print("\n-- 事件序列 --")
    for e in events:
        t = e.get("type")
        d = e.get("data") if isinstance(e.get("data"), dict) else {}
        if t == "assistant/message":
            msg = d.get("message") if isinstance(d.get("message"), dict) else d
            content = msg.get("content")
            kinds = [b.get("type") for b in content if isinstance(b, dict)] if isinstance(content, list) else type(content).__name__
            texts = [str(b.get("text", ""))[:120] for b in content
                     if isinstance(b, dict) and b.get("type") == "text"] if isinstance(content, list) else []
            print(f"  {t}: blocks={kinds} text={texts}")
        elif t == "turn/end":
            print(f"  {t}: reason={d.get('reason')}")
        elif t in ("agent/message", "user/message", "system/message"):
            print(f"  {t}: {str(d)[:150]}")
        else:
            print(f"  {t}: {str(d)[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
