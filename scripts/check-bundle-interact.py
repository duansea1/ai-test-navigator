# -*- coding: utf-8 -*-
"""校验新交互标记全部进了 dist bundle。"""
import io
s = io.open(r'C:/Akua/ai-test-navigator/frontend/dist/assets/app.js', encoding='utf-8').read()
esc = '\\' + 'u'
def esc_of(t):
    return ''.join(c if ord(c) < 128 else f'{esc}{ord(c):04X}' for c in t)
tests = [
    '正在思考…',
    'c-edit',
    'thinking-hint',
    '双击重命名',
    'PATCH',
    'method:"PATCH"',
]
bad = 0
for t in tests:
    ok = (t in s) or (esc_of(t) in s)
    if not ok:
        bad += 1
    print(('OK   ' if ok else 'MISS ') + t)
print('FAIL' if bad else 'ALL PASS')
