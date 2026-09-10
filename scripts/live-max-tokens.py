# -*- coding: utf-8 -*-
"""live 验证（M3.8 网关 max_tokens 钳制）：glm-5.3-flash @ 宝云。
前置：8090 需跑已改代码（uvicorn 需重启加载新 runtime.py/agents.py）。
步骤：
  1) 无需切模型（当前就是 glm-5.3-flash），直接发 /api/chat/stream
  2) 期望：answer 非空、无 model_error —— 修复前报
     「max_tokens参数非法：限制数值范围[1,131072]」
"""
import json, sys, urllib.request, urllib.error, uuid

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = 'http://127.0.0.1:8090'
cid = f'conv-live-{uuid.uuid4().hex[:8]}'

body = {'text': '你好，一句话介绍你自己', 'conversation_id': cid}
req = urllib.request.Request(
    BASE + '/api/chat/stream',
    data=json.dumps(body).encode(),
    headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req, timeout=300) as r:
        answer, model_error, reason = '', None, ''
        for line in r:
            line = line.decode('utf-8', 'replace').strip()
            if not line.startswith('data: '):
                continue
            try:
                d = json.loads(line[6:])
            except Exception:
                continue
            if 'answer' in d:
                answer = d.get('answer') or ''
                model_error = d.get('model_error')
                reason = d.get('reason') or ''
        print('answer[:120]:', answer[:120].replace('\n', ' '))
        print('model_error:', model_error)
        print('reason:', reason[:80])
        ok = bool(answer) and not model_error and '模型调用失败' not in answer
        print('RESULT:', 'PASS' if ok else 'FAIL')
        sys.exit(0 if ok else 1)
except urllib.error.HTTPError as e:
    print('HTTP', e.code, e.read().decode('utf-8', 'replace')[:300])
    sys.exit(1)
