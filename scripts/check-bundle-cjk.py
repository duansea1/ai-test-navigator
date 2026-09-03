# -*- coding: utf-8 -*-
"""验证 dist/assets/app.js 中新弹框的类名与中文文案都在（bundle CJK 校验法）。"""
import io, sys

s = io.open(r'C:/Akua/ai-test-navigator/frontend/dist/assets/app.js', encoding='utf-8').read()
esc = '\\' + 'u'

def esc_of(text: str) -> str:
    # esbuild 会把非 ASCII 转成 \uXXXX 转义
    return ''.join(c if ord(c) < 128 else f'{esc}{ord(c):04X}' for c in text)

tests = [
    'mc-head', 'mc-nav-head', 'mc-nav-item', 'mc-detail-head',
    'mc-summary', 'mc-provider-status', 'mc-model-state', 'mc-models',
    '使用中', '选用', '添加供应商', '恢复默认供应商',
    '测试连接', '设为默认',
    # M3.9.1 模型市场：旧空态文案「该供应商未配置模型」已被模型市场空态取代
    '拉取全部模型', '搜索模型', 'mc-market', 'mc-pull',
]
bad = 0
for t in tests:
    ok = (t in s) or (esc_of(t) in s)
    if not ok:
        bad += 1
    print(('OK      ' if ok else 'MISSING ') + t)
print('FAIL' if bad else 'ALL PASS')
sys.exit(1 if bad else 0)
