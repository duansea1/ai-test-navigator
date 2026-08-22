"""DB 层冒烟：MySQL 建表 + CRUD + SQLite 降级 + JSON 提取。

用法：python scripts/smoke-db.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    from app.core.config import get_settings
    from app.db import engine, entities

    print(f"连接串：{get_settings().database_url}")
    engine.init_schema()
    print("1) init_schema OK（10 表，可重复执行）")

    # 任务 CRUD
    task_id = entities.create_task("冒烟任务：登录锁定", "用户连续输错密码5次锁定30分钟。", "proj-a", "integration", r"C:\Akua")
    task = entities.get_task(task_id)
    assert task and task["status"] == "pending", task
    print(f"2) create/get task OK：{task_id}")

    entities.update_task(task_id, status="running", stage="dsh-parse", progress=55, message="解析中")
    task = entities.get_task(task_id)
    assert task["progress"] == 55 and task["stage"] == "dsh-parse", task
    print("3) update task OK")

    # 需求条目
    items = [
        {"id": "REQ-01", "title": "错误计数", "description": "记录连续输错次数", "priority": "P0", "acceptance_criteria": ["第5次触发锁定"]},
        {"id": "REQ-02", "title": "锁定提示", "description": "统一话术", "priority": "P1", "acceptance_criteria": []},
    ]
    n = entities.save_requirements(task_id, items)
    rows = entities.list_requirements(task_id)
    assert n == 2 and len(rows) == 2 and rows[0]["acceptance_criteria"] == ["第5次触发锁定"], rows
    print(f"4) requirements save/list OK（{n} 条，JSON 往返一致）")

    # 报告 + 聚合
    entities.save_report(task_id, "RPT-smoke01", {"html": "/reports/RPT-smoke01.html"}, {"requirements": 2})
    stats = entities.dashboard_stats()
    assert stats["tasks_total"] >= 1 and stats["requirements_total"] >= 2, stats
    trend = entities.dashboard_trend(7)
    assert isinstance(trend, list), trend
    print(f"5) report/dashboard 聚合 OK：{stats}")

    # 清理冒烟数据
    engine.execute("DELETE FROM requirements WHERE task_id = ?", (task_id,))
    engine.execute("DELETE FROM reports WHERE report_id = ?", ("RPT-smoke01",))
    engine.execute("DELETE FROM analysis_tasks WHERE task_id = ?", (task_id,))
    print("6) 冒烟数据已清理")

    # orchestrator JSON 提取
    from app.services.orchestrator import _extract_items

    fenced = '前置说明\n```json\n{"items": [{"id": "REQ-01", "title": "t", "priority": "P0", "acceptance_criteria": ["a"]}]}'
    out = _extract_items(fenced)
    assert out and out[0]["id"] == "REQ-01" and out[0]["acceptance_criteria"] == ["a"], out
    assert _extract_items("模型拒绝：无法解析") is None
    print("7) _extract_items OK（围栏/裸 JSON/噪声容错）")
    return 0


def smoke_sqlite() -> int:
    """SQLite 降级冒烟（子进程方式重载配置）。"""
    import os
    import subprocess
    import tempfile

    db_path = Path(tempfile.mkdtemp()) / "smoke.db"
    env = {**os.environ, "AI_NAVIGATOR_DB": f"sqlite:///{db_path}".replace("\\", "/")}
    code = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s');"
         "from app.db import engine, entities;"
         "engine.init_schema();"
         "tid = entities.create_task('sqlite 冒烟', '文本', 'p', 'b', 'w');"
         "assert entities.get_task(tid)['status'] == 'pending';"
         "entities.save_requirements(tid, [{'id': 'REQ-01', 'title': 't', 'description': 'd', 'priority': 'P1', 'acceptance_criteria': []}]);"
         "assert len(entities.list_requirements(tid)) == 1;"
         "print('SQLite 降级 OK')" % str(BACKEND)],
        env=env, capture_output=True, text=True,
    )
    print(code.stdout.strip() or code.stderr.strip()[-500:])
    return code.returncode


if __name__ == "__main__":
    rc = main()
    rc |= smoke_sqlite()
    print("\n全部通过" if rc == 0 else f"\n失败（exit {rc}）")
    raise SystemExit(rc)
