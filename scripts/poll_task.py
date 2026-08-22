import sys, time, urllib.request, json

TASK_ID = "task-c0a8418fff04"
BASE = "http://localhost:8090"

def get(url):
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

for i in range(20):
    try:
        t = get(f"{BASE}/api/requirements/tasks/{TASK_ID}")
    except Exception as e:
        print(f"[{i}] poll error: {e}")
        time.sleep(15)
        continue
    print(f"[{i}] stage={t.get('stage')} prog={t.get('progress')} status={t.get('status')} report={t.get('report_id')} msg={t.get('message')}")
    if t.get("status") in ("completed", "failed"):
        print("FINAL:", json.dumps(t, ensure_ascii=False)[:2000])
        break
    time.sleep(15)
