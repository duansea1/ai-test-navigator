# -*- coding: utf-8 -*-
"""live 冒烟：模型调用错误显式化 + base_url 归一化（M3.6「模型未返回内容」修复）。

场景：
  ① 切 gpt-5.6-luna（baoyun 网关，base_url 无 /v1——归一化后应可用）：
     probe.ok=True + 问 hello 得到真实回答（用户原始场景修复验证）
  ② 造临时坏模型（不存在的模型名）→ probe.ok=False + 404 真因；
     问答终帧带 model_error（含 404），回答明示失败与换模型指引
  ③ 清理临时配置，切回 deepseek-v4-flash → probe.ok=True 正常回答
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8090"
BOUNDARY = "----livemodelerror001"


def req_json(path: str, payload: dict, method: str = "POST", timeout: int = 90) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode("utf-8"), method=method,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def delete(path: str) -> None:
    req = urllib.request.Request(BASE + path, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
    except Exception:
        pass


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


def chat_done(text: str) -> dict:
    evs = post_sse("/api/chat/stream", {"text": text})
    done = [e for e in evs if e.get("done")]
    return done[0] if done else {}


def main() -> int:
    fails = []
    luna_key = sys.argv[1] if len(sys.argv) > 1 else "gpt-5.6-luna"
    good_key = sys.argv[2] if len(sys.argv) > 2 else "deepseek-v4-flash"
    bad_key = "smoke-bad-model-404"

    # ── ① gpt-5.6-luna（baoyun 网关）：base_url 归一化修掉 404 后，网关
    #    不认 DSH 的 thinking 参数——切换探测应如实报出（带同款参数探测），
    #    问答终帧 model_error 也应可见（不再「模型未返回内容」黑盒）──
    cfg = req_json("/api/agents/runtime/config", {"provider_key": luna_key})
    probe = cfg.get("probe") or {}
    print(f"[1] 切 {luna_key}：probe.ok={probe.get('ok')} err={str(probe.get('error'))[:70]}")
    d = chat_done("hello")
    ans = d.get("answer") or ""
    print(f"    问答：model_error={str(d.get('model_error'))[:70]}")
    if probe.get("ok") is True:
        # 网关若兼容 thinking 则应真正可用
        if d.get("model_error") or len(ans) < 5:
            fails.append(f"步骤1 探测通过但问答失败：{d.get('model_error')}")
    else:
        # 探测失败 = 网关不兼容，错误应具体可行动（404/thinking/参数），
        # 且问答侧同样可见真因——关键不变式：绝不静默空白
        if not str(probe.get("error")) or len(str(probe.get("error"))) < 5:
            fails.append(f"步骤1 探测失败但无具体原因：{probe}")
        if not d.get("model_error"):
            fails.append(f"步骤1 问答终帧缺 model_error：{d}")
        elif "404" not in (d.get("model_error") or "") and "thinking" not in (d.get("model_error") or "") \
                and "Unknown parameter" not in (d.get("model_error") or ""):
            fails.append(f"步骤1 model_error 非预期真因：{d.get('model_error')!r}")
        if "模型调用失败" not in ans:
            fails.append(f"步骤1 回答未明示失败：{ans[:60]!r}")

    # ── ② 临时坏模型：404 显式化（deepseek 官方端点 + 不存在的模型名；
    #    api_key 留空 → 探测/运行时回退 settings 的 DeepSeek Key）──
    req_json(f"/api/agents/runtime/config/models/{bad_key}", {
        "display_name": "冒烟临时坏模型", "base_url": "https://api.deepseek.com/v1",
        "model_ids": ["no-such-model-xyz-404"], "enabled": True})
    try:
        cfg2 = req_json("/api/agents/runtime/config", {"provider_key": bad_key})
        probe2 = cfg2.get("probe") or {}
        print(f"[2] 切坏模型：probe.ok={probe2.get('ok')} err={str(probe2.get('error'))[:60]}")
        if probe2.get("ok") is not False:
            fails.append(f"步骤2 坏模型探测未报错：{probe2}")
        d2 = chat_done("hello")
        ans2 = d2.get("answer") or ""
        print(f"    问答：model_error={str(d2.get('model_error'))[:60]}")
        print(f"    回答：{ans2[:80]!r}")
        if not d2.get("model_error"):
            fails.append(f"步骤2 终帧缺 model_error：{d2}")
        elif "404" not in d2["model_error"] and "400" not in d2["model_error"] and "401" not in d2["model_error"]:
            fails.append(f"步骤2 model_error 未含 HTTP 错误码：{d2['model_error']!r}")
        if "模型调用失败" not in ans2:
            fails.append(f"步骤2 回答未明示失败：{ans2[:60]!r}")
    finally:
        delete(f"/api/agents/runtime/config/models/{bad_key}")

    # ── ③ 切回好模型恢复正常 ──
    cfg3 = req_json("/api/agents/runtime/config", {"provider_key": good_key})
    probe3 = cfg3.get("probe") or {}
    print(f"[3] 切回 {good_key}：probe.ok={probe3.get('ok')}")
    if probe3.get("ok") is not True:
        fails.append(f"步骤3 好模型探测失败：{probe3}")
    else:
        d3 = chat_done("你好")
        ans3 = d3.get("answer") or ""
        print(f"    问答：{ans3[:60]!r}")
        if d3.get("model_error") or len(ans3) < 10:
            fails.append(f"步骤3 好模型问答异常：{d3.get('model_error')}")

    print()
    if fails:
        print("FAIL ×%d" % len(fails))
        for f in fails:
            print(" -", f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
