import sys

sys.path.insert(0, "backend")
from app.db import engine

rows = engine.query(
    "SELECT task_id, status, stage, progress, error FROM analysis_tasks ORDER BY id DESC LIMIT 3")
for r in rows:
    print(r)
cols = [c["Field"] for c in engine.query("SHOW COLUMNS FROM assessments")] \
    if engine.query("SHOW COLUMNS FROM assessments") else []
print("assessments 列：", cols)
