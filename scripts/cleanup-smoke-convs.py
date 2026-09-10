# -*- coding: utf-8 -*-
"""清理 live 冒烟产生的测试会话（scripts/live-chat-stream.py 的副作用数据）。"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8090"
# 冒烟轮次产生的会话标题（两轮：乱码输出轮 + UTF-8 输出轮）
TITLES = {
    "你好，请用一句话介绍你能做什么？",
    "这个项目的登录逻辑该怎么测？",
    "新会话",           # 附件-only：t 为空时标题兜底
    "分析这张图",
}

def main() -> int:
    with urllib.request.urlopen(f"{BASE}/api/conversations?limit=30", timeout=10) as r:
        convs = json.load(r)["conversations"]
    deleted = 0
    for c in convs:
        if c.get("title") in TITLES:
            req = urllib.request.Request(f"{BASE}/api/conversations/{c['conv_id']}",
                                         method="DELETE")
            with urllib.request.urlopen(req, timeout=10) as r:
                r.read()
            deleted += 1
            print("deleted", c["conv_id"], c["title"])
    print(f"total deleted: {deleted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
