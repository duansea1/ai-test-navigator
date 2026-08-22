"""DSH Runtime 冒烟测试：源码注入 → node 载体启动 → JSON-RPC 握手 → 一个回合。

用法：python scripts/smoke-dsh.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402
from app.dsh.runtime import manager  # noqa: E402


def main() -> int:
    s = get_settings()
    print(f"源码集成：{s.dsh_source_available}")
    print(f"node 载体：{s.dsh_node_carrier_available}")
    print(f"凭据配置：{s.dsh_credential_configured}")
    print(f"DSH 就绪：{s.dsh_ready}")

    print("\n启动 Runtime ...")
    ok = manager.start()
    print(f"启动结果：{ok}")
    print(json.dumps(manager.availability(), ensure_ascii=False, indent=2))
    if not ok:
        return 1

    print("\n执行一个回合（验证满血组合挂载）...")
    raw = manager._harness.run("请只回复两个字：就绪")

    # 从事件流提取模型可见的工具目录（比模型自报更可靠）
    import re

    tools: set[str] = set()
    for e in raw.events:
        text = json.dumps(e, ensure_ascii=False)
        for m in re.findall(r'"name"\s*:\s*"([a-zA-Z_]+)"', text):
            tools.add(m)
    expected = {
        "subagent": "原生子代理",
        "subagent_fork": "子代理 fork",
        "subagent_claude_code": "Claude Code 子代理",
        "workflow": "工作流",
        "skill": "Skills",
        "todo_write": "todo",
        "write": "文件系统写入",
        "grep": "代码检索",
    }
    print("\n工具目录（事件流扫描）：")
    for name in sorted(tools):
        mark = expected.get(name)
        print(f"  {name}{'  ← ' + mark if mark else ''}")
    missing = [n for n in expected if n not in tools]
    print(f"\n满血关键能力缺失：{missing if missing else '无（全部就位）'}")
    print(f"finish_reason：{raw.finish_reason}，事件数：{len(raw.events)}")
    print(f"模型回复：{(raw.final_response or '')[:200]}")
    manager.stop()
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
