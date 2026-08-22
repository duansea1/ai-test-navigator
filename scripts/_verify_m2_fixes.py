"""M2 修复验证：僵尸任务清理 + views 提取兼容（只读，不干扰运行中任务）。"""
import sys
import urllib.request

sys.path.insert(0, "backend")
from app.db import engine  # noqa: E402

# 1) 僵尸任务清理
stale = engine.query(
    "SELECT task_id, status, error FROM analysis_tasks WHERE stage = 'interrupted'")
print(f"1) 僵尸任务已清理：{len(stale)} 个")
for r in stale:
    print(f"   {r['task_id']} → {r['status']}（{r['error']}）")
running = engine.query("SELECT task_id, stage FROM analysis_tasks WHERE status IN ('pending','running')")
print(f"   当前运行中：{[(r['task_id'], r['stage']) for r in running]}")

# 2) views 提取兼容（单元级：裸 dict / 包裹 dict 两种模型输出形态）
from app.services.orchestrator import _extract_json  # noqa: E402

bare = '{"dev": "研发视角摘要", "qa": "测试视角摘要", "product": "产品视角摘要"}'
wrapped = '{"views": {"dev": "研发视角摘要", "qa": "测试视角摘要", "product": "产品视角摘要"}}'

for text, label in [(bare, "裸 dict"), (wrapped, "包裹 dict")]:
    raw = _extract_json(text, keys=("views",))
    views = raw.get("views") if isinstance(raw, dict) and isinstance(raw.get("views"), dict) else raw
    ok = isinstance(views, dict) and any(views.get(k) for k in ("dev", "qa", "product"))
    print(f"2) views 提取 [{label}]：{'OK' if ok else 'FAIL'} → {views}")

# 3) 服务健康
health = urllib.request.urlopen("http://127.0.0.1:8010/api/health", timeout=10).read().decode()
print(f"3) 服务健康：{health[:80]}")
