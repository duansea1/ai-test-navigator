"""直接 import 磁盘上的真实函数，定位 test 链路。"""
import json
import sys

sys.path.insert(0, r"c:\Akua\ai-test-navigator\backend")

import urllib.request
# 清掉可能从 shell 继承的代理，模拟 start.ps1 启动环境
for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
    os_env = __import__("os").environ
    os_env.pop(k, None)

from app.api import agents

payload = {"base_url": "https://ai-api.baoyun.com"}
print("=== _resolve_test_target(gpt-5.6-luna, payload) ===")
ok, bu, ak = agents._resolve_test_target("gpt-5.6-luna", payload)
print("ok=", ok, "| base_url=", bu, "| api_key_prefix=", (ak[:6] + "..." if ak else ak))

print("\n=== _http_get_models(真实调用) ===")
ok2, data = agents._http_get_models(bu, ak)
print("ok=", ok2)
if isinstance(data, dict):
    print("error=", data.get("error"))
    d = data.get("data")
    print("data is list?", isinstance(d, list), "len=", len(d) if isinstance(d, list) else None)
else:
    print("data type=", type(data), "raw=", str(data)[:200])

print("\n=== test_model(真实调用, 模拟 POST body) ===")
res = agents.test_model("gpt-5.6-luna", payload)
print(json.dumps(res, ensure_ascii=False)[:400])
