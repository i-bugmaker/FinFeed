#!/usr/bin/env python3
"""一次性迁移：硬编码 font-size px → 字号刻度令牌（v4.5 可读性修正）。

映射（≤12.5px 一律提升到地板之上；半 px 收敛；整 px 等值换令牌）：
  9/10/10.5px → var(--ff-fs-micro) 11
  11/11.5/12px → var(--ff-fs-xs) 12
  12.5/13/13.5px → var(--ff-fs-caption) 13
  14/14.5px → var(--ff-fs-body-sm) 14
  15px → var(--ff-fs-body) 15
  16px → var(--ff-fs-h4) 16
  17px → var(--ff-fs-h3) 17
  18px → var(--ff-fs-data-lg) 18
tokens.css（令牌定义本体）跳过；21/22/24/28/32 大字号单独人工处理。
"""
import io
import os
import re

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'src'))

M = [
    ('9px', 'var(--ff-fs-micro)'),
    ('10px', 'var(--ff-fs-micro)'),
    ('10.5px', 'var(--ff-fs-micro)'),
    ('11px', 'var(--ff-fs-xs)'),
    ('11.5px', 'var(--ff-fs-xs)'),
    ('12px', 'var(--ff-fs-xs)'),
    ('12.5px', 'var(--ff-fs-caption)'),
    ('13px', 'var(--ff-fs-caption)'),
    ('13.5px', 'var(--ff-fs-caption)'),
    ('14px', 'var(--ff-fs-body-sm)'),
    ('14.5px', 'var(--ff-fs-body-sm)'),
    ('15px', 'var(--ff-fs-body)'),
    ('16px', 'var(--ff-fs-h4)'),
    ('17px', 'var(--ff-fs-h3)'),
    ('18px', 'var(--ff-fs-data-lg)'),
]
PAT = re.compile(r'font-size:\s*([0-9.]+)px')
TOK = {px: tok for px, tok in M}

changed = 0
total_subs = 0
for base, dirs, files in os.walk(ROOT):
    for fn in files:
        if not fn.endswith(('.vue', '.css')):
            continue
        path = os.path.join(base, fn)
        rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
        if rel == 'styles/tokens.css':
            continue
        with io.open(path, encoding='utf-8') as f:
            s = f.read()
        n = [0]

        def rep(m):
            v = m.group(1) + 'px'
            if v in TOK:
                n[0] += 1
                return 'font-size: ' + TOK[v]
            return m.group(0)

        s2 = PAT.sub(rep, s)
        if n[0]:
            with io.open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(s2)
            changed += 1
            total_subs += n[0]
            print(f'{rel}: {n[0]}')
print(f'--- 文件 {changed} 个，替换 {total_subs} 处')
