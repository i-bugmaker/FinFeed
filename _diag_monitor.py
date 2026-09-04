import json
import sqlite3

c = sqlite3.connect(r'E:\VibeCoding\FinFeed\finfeed\news_monitor.db')
c.row_factory = sqlite3.Row
rows = c.execute('SELECT code,name FROM stock_watchlist').fetchall()
for r in rows:
    code = r['code']
    name = (r['name'] or '').strip()
    q = c.execute(
        'SELECT id,title,category,stocks FROM news WHERE title LIKE ? OR title LIKE ? OR stocks LIKE ? '
        'ORDER BY publish_ts DESC,id DESC LIMIT 10',
        ('%' + code + '%', '%' + name + '%', '%"' + code + '"%')
    ).fetchall()
    print('===', code, name, '命中', len(q))
    for it in q:
        st = json.loads(it['stocks']) if it['stocks'] and it['stocks'].strip() not in ('', '[]') else []
        hit_st = code in st
        t = it['title'] or ''
        hit_t = code in t or name in t
        tag = '[STOCKED]' if hit_st else ('[title-only]' if hit_t else '[code-only]')
        print('   ', (it['category'] or ''), '|', t[:42], tag)
