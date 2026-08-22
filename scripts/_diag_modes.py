"""验证意图路由三模式：classify / chat / analyze 任务。"""
import json
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8090"


def post_form(path, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(BASE + path, data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read().decode("utf-8")


def get_json(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


print("=== 1) classify: 你有什么能力 ===")
_, c = post_form("/api/requirements/classify", {"text": "你有什么能力"})
print(c)

print("\n=== 2) chat: 你有什么能力 ===")
_, a = post_form("/api/chat", {"text": "你有什么能力"})
d = json.loads(a)
print("answer:", d.get("answer", "")[:200])

print("\n=== 3) 创建 analyze 模式任务 ===")
_, t = post_form("/api/requirements/tasks", {
    "text": "新增订单导出功能，支持按状态筛选并导出为 Excel",
    "mode": "analyze", "projects": "自动侦察", "workspace": "", "branch": ""})
task = json.loads(t)
tid = task["task_id"]
print("task_id:", tid)

print("=== 4) 轮询任务状态（最多 90s） ===")
for i in range(30):
    st = get_json(f"/api/requirements/tasks/{tid}")
    print(f"  [{i*3}s] status={st['status']} progress={st.get('progress')} stage={st.get('stage')}")
    if st["status"] in ("completed", "failed"):
        print("  done. 报告:", st.get("report_id"))
        break
    time.sleep(3)
