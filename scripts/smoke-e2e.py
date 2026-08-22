"""M1 端到端验证：创建分析任务 → 轮询至终态 → 校验需求入库与 dashboard。

用法：python scripts/smoke-e2e.py [port]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = f"http://127.0.0.1:{sys.argv[1] if len(sys.argv) > 1 else '8010'}"
REQ_TEXT = (
    "电商订单系统需求：1）用户下单后 30 分钟未支付自动取消订单并释放库存；"
    "2）取消和释放必须幂等，重复触发不产生二次扣减；"
    "3）库存不足时下单失败，返回明确错误码 GOODS_OUT_OF_STOCK。"
)


def call(path: str, method: str = "GET", body: bytes | None = None, form: bytes | None = None, timeout: int = 60) -> dict:
    headers = {}
    data = None
    if body is not None:
        data = body
        headers["Content-Type"] = "application/json"
    if form is not None:
        data = form
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())


def main() -> int:
    # 1) 创建任务（URL 编码表单）
    form = "text=" + urllib.request.quote(REQ_TEXT) + "&projects=demo-order&branch=integration"
    created = call("/api/requirements/tasks", "POST", form=form.encode())
    task_id = created["task_id"]
    print(f"1) 任务创建：{task_id}")

    # 2) 轮询至终态（8-Agent 流水线约 3-8 分钟）
    deadline = time.time() + 900
    task = {}
    while time.time() < deadline:
        task = call(f"/api/requirements/tasks/{task_id}")
        print(f"   [{task['status']}] {task['stage']} {task['progress']}% - {(task.get('message') or '')[:60]}")
        if task["status"] in ("completed", "failed"):
            break
        time.sleep(2)
    if task.get("status") != "completed":
        print(f"失败：{task.get('error')}")
        return 1
    print(f"2) 任务完成：报告 {task.get('report_id')}")

    # 3) 需求条目
    items = call(f"/api/requirements/tasks/{task_id}/requirements")["items"]
    assert len(items) >= 2, f"需求条目过少：{len(items)}"
    assert all("id" in it and "title" in it for it in items), items
    for it in items:
        print(f"   {it['id']} [{it['priority']}] {it['title']}（验收标准 {len(it['acceptance_criteria'])} 条）")

    # 4) 任务列表 + dashboard
    tasks = call("/api/requirements/tasks?limit=5")["tasks"]
    assert any(t["task_id"] == task_id for t in tasks), "任务列表未见新任务"
    dash = call("/api/dashboard")
    assert dash["source"] == "db", f"dashboard 数据源异常：{dash.get('source')}"
    assert dash["totals"]["tasks_total"] >= 1 and dash["totals"]["requirements"] >= len(items), dash["totals"]
    print(f"4) dashboard（db 源）：{dash['totals']}，趋势 {len(dash['trend'])} 天")
    print("\n端到端验证全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
