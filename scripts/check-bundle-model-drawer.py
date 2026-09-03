# -*- coding: utf-8 -*-
"""校验模型市场新交互标记进 bundle。"""
import io
s = io.open(r'C:/Akua/ai-test-navigator/frontend/dist/assets/app.js', encoding='utf-8').read()
esc = '\\' + 'u'
def esc_of(t):
    return ''.join(c if ord(c) < 128 else f'{esc}{ord(c):04X}' for c in t)
tests = [
    '拉取全部模型',
    '搜索模型',
    'mc-market',
    'mc-search',
    'mc-pull',
    'mc-new-tag',
    'fetch-available',
    '拉取可用模型',
    '已选用',
]
bad = 0
for t in tests:
    ok = (t in s) or (esc_of(t) in s)
    if not ok:
        bad += 1
    print(('OK   ' if ok else 'MISS ') + t)
print('FAIL' if bad else 'ALL PASS')
