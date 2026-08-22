"""一次性诊断：复现旧接口返回 + 用修复后逻辑直连 baoyun 验证。"""
import json
import sys
import urllib.error
import urllib.request

import pymysql

# ── 1) 复现：对正在运行的旧进程(2288)发请求 ──────────────────────────────
def post_live():
    body = json.dumps({"base_url": "https://ai-api.baoyun.com"}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:8090/api/agents/runtime/config/models/gpt-5.6-luna/test",
        data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")

# ── 2) 取库里真实配置 ─────────────────────────────────────────────────────
def db_configs():
    conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="root",
                           database="ai-navigator", charset="utf8mb4")
    try:
        cur = conn.cursor(pymysql.cursors.DictCursor)
        cur.execute("SELECT provider_key, base_url, api_key, model_ids FROM model_configs")
        return cur.fetchall()
    finally:
        conn.close()

# ── 3) 修复后逻辑：先 /models 再 /v1/models ──────────────────────────────
def http_get_models(base_url, api_key):
    if not base_url:
        return False, {"error": "未配置 API 地址"}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    last = {"error": "未探测到可用端点"}
    for path in ("/models", "/v1/models"):
        url = base_url.rstrip("/") + path
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return True, url, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                last = json.loads(e.read().decode("utf-8"))
            except Exception:
                last = {"error": f"HTTP {e.code}"}
            if e.code == 401:
                return False, url, last
        except Exception as exc:
            last = {"error": f"{type(exc).__name__}: {exc}"}
    return False, url, last

def main():
    print("=== 1) 复现旧进程(2288)返回 ===")
    try:
        st, ct = post_live()
        print(f"HTTP {st}: {ct}")
    except Exception as e:
        print(f"live 请求异常: {e}")

    print("\n=== 2) 库里模型供应商配置 ===")
    try:
        cfgs = db_configs()
        for c in cfgs:
            mask = (c["api_key"][:4] + "****" + c["api_key"][-4:]) if c["api_key"] and len(c["api_key"]) > 8 else (c["api_key"] or "")
            print(f"- {c['provider_key']} | base_url={c['base_url']} | key={mask} | model_ids={c['model_ids']}")
    except Exception as e:
        print(f"读库异常: {e}")
        cfgs = []

    print("\n=== 3) 用修复后逻辑直连 baoyun ===")
    # 找 baoyun 相关配置
    target = None
    for c in cfgs:
        if "baoyun" in (c["provider_key"] or "").lower() or "baoyun" in (c["base_url"] or "").lower():
            target = c
            break
    if target is None:
        # 退而用 gpt-5.6-luna 或第一个带 api_key 的
        for c in cfgs:
            if c["api_key"]:
                target = c
                break
    if target:
        print(f"用配置: {target['provider_key']} base_url={target['base_url']}")
        ok, used_url, data = http_get_models(target["base_url"], target["api_key"])
        if ok:
            ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
            print(f"OK via {used_url}, 模型数={len(ids)}, 前5: {ids[:5]}")
        else:
            print(f"FAIL via {used_url}, error={data}")
    else:
        print("库里没有带 api_key 的可用配置")

if __name__ == "__main__":
    main()
