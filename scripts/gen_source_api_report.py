#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「快讯」与「财经」两个模块的数据源 API 清单报告。"""

import datetime as dt
import os
import sqlite3

from finfeed.config.article_sources import ARTICLE_NEWS_SOURCES
from finfeed.config.flash_sources import FLASH_NEWS_SOURCES

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  'finfeed', 'news_monitor.db')
OUT_DIR = os.path.join(os.path.expanduser('~'), 'Desktop')
TZ = dt.timezone(dt.timedelta(hours=8))


def load_health():
    if not os.path.exists(DB):
        return {}
    con = sqlite3.connect(DB)
    try:
        health = {}
        for row in con.execute(
            'select source_name,total_requests,success_count,failure_count,'
            'consecutive_failures,avg_latency,last_success_ts,last_failure_ts,'
            'last_error,is_circuit_open from source_health'
        ):
            health[row[0]] = {
                'total': row[1], 'succ': row[2], 'fail': row[3],
                'consec_fail': row[4], 'latency': row[5],
                'last_ok': row[6], 'last_err_ts': row[7],
                'last_error': row[8] or '', 'circuit_open': row[9],
            }
        return health
    finally:
        con.close()


def classify(src):
    """按 Accept 头与 parser 推断接口形态。

    注意排除 application/xhtml+xml 对 'xml' 关键字的误命中。
    """
    accept = (src.headers or {}).get('Accept', '')
    if src.parser_type == 'rss' or 'rss+xml' in accept or accept.startswith('application/atom+xml'):
        return 'RSS/Atom'
    if 'application/json' in accept:
        return 'JSON API'
    if 'text/html' in accept:
        return 'HTML 抓取'
    if accept.startswith('*/*'):
        return 'JS/文本'
    return '其他'


def fmt_ts(ts):
    if not ts:
        return '—'
    return dt.datetime.fromtimestamp(ts, TZ).strftime('%m-%d %H:%M')


def grade(h):
    """健康等级：正常 / 轻微劣化 / 高风险"""
    if not h:
        return '未知', ''
    rate = h['succ'] / h['total'] * 100 if h['total'] else 0
    if h['circuit_open'] or h['consec_fail'] >= 3:
        return '🔴 熔断/连续失败', f'{rate:.1f}%'
    if rate >= 99.0:
        return '🟢 正常', f'{rate:.1f}%'
    if rate >= 95.0:
        return '🟡 轻微劣化', f'{rate:.1f}%'
    return '🟠 高风险', f'{rate:.1f}%'


def params_str(src):
    if not src.params:
        return '—'
    return ', '.join(f'`{k}={v}`' for k, v in src.params.items())


def build_table(sources, health):
    lines = [
        '| # | 来源 | 接口类型 | 方法 | API 端点 | 解析器 | 成功率 | 均延迟 | 最近成功 | 状态 |',
        '|---|------|----------|------|----------|--------|--------|--------|----------|------|',
    ]
    for i, s in enumerate(sources, 1):
        h = health.get(s.name)
        status, rate = grade(h)
        lat = f"{h['latency']:.2f}s" if h and h['latency'] else '—'
        last_ok = fmt_ts(h['last_ok']) if h else '—'
        lines.append(
            f"| {i} | {s.name} | {classify(s)} | {s.method} | "
            f"`{s.url}` | `{s.parser_type}` | {rate} | {lat} | {last_ok} | {status} |"
        )
    return '\n'.join(lines)


def build_detail(sources, health):
    blocks = []
    for s in sources:
        h = health.get(s.name)
        status, rate = grade(h)
        lines = [f'### {s.name}', '']
        lines.append(f'- **端点**：`{s.url}`')
        lines.append(f'- **方法**：`{s.method}`　|　**接口类型**：{classify(s)}　|　**解析器**：`{s.parser_type}`')
        if s.params:
            lines.append(f'- **默认参数**：{params_str(s)}')
        key_headers = {k: v for k, v in (s.headers or {}).items()
                       if k in ('Referer', 'Content-Type', 'Origin', 'Cookie')}
        if key_headers:
            lines.append('- **关键请求头**：' + '；'.join(f'`{k}: {v}`' for k, v in key_headers.items()))
        if not s.verify_ssl:
            lines.append('- **注意**：已关闭 SSL 证书校验（`verify_ssl=False`）')
        if h:
            lines.append(
                f'- **运行状况**：成功率 {rate}（{h["succ"]}/{h["total"]}），'
                f'平均延迟 {h["latency"]:.2f}s，连续失败 {h["consec_fail"]} 次'
            )
            lines.append(f'- **最近成功**：{fmt_ts(h["last_ok"])}　|　**最近失败**：{fmt_ts(h["last_err_ts"])}')
            if h['last_error']:
                lines.append(f'- **最近错误**：`{h["last_error"][:80]}`')
        lines.append(f'- **健康判定**：{status}')
        lines.append('')
        blocks.append('\n'.join(lines))
    return '\n'.join(blocks)


def main():
    health = load_health()
    now = dt.datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')

    def stat(sources):
        total = len(sources)
        ok = sum(1 for s in sources if grade(health.get(s.name))[0].startswith('🟢'))
        warn = sum(1 for s in sources if '🟡' in grade(health.get(s.name))[0])
        risk = sum(1 for s in sources if ('🟠' in grade(health.get(s.name))[0]
                                          or '🔴' in grade(health.get(s.name))[0]))
        api = sum(1 for s in sources if classify(s) == "JSON API")
        html = sum(1 for s in sources if classify(s) == "HTML 抓取")
        rss = sum(1 for s in sources if classify(s) == "RSS/Atom")
        js = sum(1 for s in sources if classify(s) == "JS/文本")
        return total, ok, warn, risk, api, html, rss, js

    f_stat = stat(FLASH_NEWS_SOURCES)
    a_stat = stat(ARTICLE_NEWS_SOURCES)

    md = f"""# FinFeed 数据源 API 清单 — 快讯 / 财经

> 生成时间：{now}（UTC+8）
> 数据源定义：`finfeed/config/flash_sources.py`、`finfeed/config/article_sources.py`
> 健康数据来源：`finfeed/news_monitor.db` → `source_health` 表

## 一、总览

| 模块 | API 路由 | 源文件 | 信源数 | JSON API | HTML 抓取 | RSS | JS | 🟢 正常 | 🟡 劣化 | 🟠/🔴 风险 |
|------|----------|--------|--------|----------|-----------|-----|----|---------|---------|------------|
| 快讯 | `/api/flash` | `flash_sources.py` | {f_stat[0]} | {f_stat[4]} | {f_stat[5]} | {f_stat[6]} | {f_stat[7]} | {f_stat[1]} | {f_stat[2]} | {f_stat[3]} |
| 财经 | `/api/articles` | `article_sources.py` | {a_stat[0]} | {a_stat[4]} | {a_stat[5]} | {a_stat[6]} | {a_stat[7]} | {a_stat[1]} | {a_stat[2]} | {a_stat[3]} |

**分类口径**（`finfeed/config/sources.py::get_source_category`）：快讯（flash）、财经（article）、舆情（forum）三集合互斥；
舆情源定义于 `sources.py::FORUM_SOURCES`，不在本报告范围内。

---

## 二、快讯模块（`/api/flash`）— {f_stat[0]} 个信源

{build_table(FLASH_NEWS_SOURCES, health)}

---

## 三、财经模块（`/api/articles`）— {a_stat[0]} 个信源

{build_table(ARTICLE_NEWS_SOURCES, health)}

---

## 四、需要关注的信源

"""
    alerts = []
    for s in FLASH_NEWS_SOURCES + ARTICLE_NEWS_SOURCES:
        h = health.get(s.name)
        if not h:
            continue
        status, rate = grade(h)
        if status.startswith('🟢'):
            continue
        err = h['last_error'][:60] if h['last_error'] else '（无记录）'
        alerts.append(
            f'- **{s.name}**（{"快讯" if s in FLASH_NEWS_SOURCES else "财经"}）：成功率 {rate}，'
            f'连续失败 {h["consec_fail"]} 次，最近错误 `{err}`'
        )
    md += ('\n'.join(alerts) if alerts else '- 无异常信源。') + '\n\n---\n\n'

    md += '## 五、快讯模块信源明细\n\n' + build_detail(FLASH_NEWS_SOURCES, health)
    md += '\n---\n\n## 六、财经模块信源明细\n\n' + build_detail(ARTICLE_NEWS_SOURCES, health)

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, 'FinFeed_数据源API清单_快讯与财经.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(md)
    print('written:', path)
    print('flash:', f_stat[0], 'article:', a_stat[0], 'alerts:', len(alerts))


if __name__ == '__main__':
    main()
