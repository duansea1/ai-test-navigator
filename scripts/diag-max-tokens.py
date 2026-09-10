# -*- coding: utf-8 -*-
"""诊断（只读不改）：glm-5.3-flash @ baoyun 网关对 max_tokens 的接受范围。
背景：DSH llm-deepseek 适配器 DEFAULT_MAX_TOKENS = 256_000，而网关报错限制 [1, 131072]。
验证假设：接口本身通（小 max_tokens 或不带都能 200），只有 DSH 默认的 256000 被拒。
Key 从 MySQL model_configs 取（与后端同源）。"""
import json, urllib.request, urllib.error, pymysql

BASE = 'https://ai-api.baoyun.com/v1/chat/completions'
MODEL = 'glm-5.3-flash'

conn = pymysql.connect(host='127.0.0.1', port=3306, user='root', password='root',
                       database='ai-navigator', charset='utf8mb4')
cur = conn.cursor()
cur.execute('SELECT api_key FROM model_configs WHERE provider_key=%s', (MODEL,))
row = cur.fetchone()
conn.close()
key = (row[0] if row else None) or ''
print('key from DB:', bool(key))

def probe(max_tokens, label):
    body = {
        'model': MODEL,
        'messages': [{'role': 'user', 'content': 'hi'}],
        'stream': False,
        'thinking': {'type': 'enabled'},
        'reasoning_effort': 'max',
    }
    if max_tokens is not None:
        body['max_tokens'] = max_tokens
    req = urllib.request.Request(
        BASE, data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    try:
        r = urllib.request.urlopen(req, timeout=60)
        d = json.loads(r.read())
        ch = (d.get('choices') or [{}])[0]
        print(f'max_tokens={label}: HTTP 200 ok, finish={ch.get("finish_reason")}')
    except urllib.error.HTTPError as e:
        print(f'max_tokens={label}: ' + f'HTTP {e.code}: ' + e.read().decode('utf-8', 'replace')[:150])

probe(None, '不带')
probe(8, '8')
probe(131072, '131072')
probe(131073, '131073')
probe(256000, '256000(=DSH默认)')
