import sys
from collections import defaultdict

sys.path.insert(0, r'E:\VibeCoding\FinFeed')
from finfeed.stock_monitor.store import get_internal_messages, list_stocks  # noqa: E402

stocks = list_stocks()
names = {s['code']: s['name'] for s in stocks}
codes = [s['code'] for s in stocks]
items = get_internal_messages(codes, names, limit=300)
# 统计每只股票命中且"标题/简介含名或代码"的数量

cnt = defaultdict(int)
samples = defaultdict(list)
for it in items:
    for code in it['codes']:
        cnt[code] += 1
        if len(samples[code]) < 5:
            samples[code].append(it.get('title', '')[:44])
for c in codes:
    print('===', c, names.get(c), '=>', cnt.get(c, 0))
    for s in samples.get(c, []):
        print('   -', s)
    if not samples.get(c):
        print('   (无相关消息)')
