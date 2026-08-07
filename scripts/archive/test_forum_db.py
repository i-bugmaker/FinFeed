import sqlite3
from config.settings import DB_PATH

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute('SELECT DISTINCT source FROM news WHERE source LIKE "%股吧%"')
sources = cursor.fetchall()
print('股吧源数据:')
for s in sources:
    cursor.execute('SELECT COUNT(*) FROM news WHERE source = ?', (s[0],))
    count = cursor.fetchone()[0]
    cursor.execute('SELECT MAX(publish_ts) FROM news WHERE source = ?', (s[0],))
    max_ts = cursor.fetchone()[0]
    print('  {}: {} items, latest ts: {}'.format(s[0], count, max_ts))

cursor.execute('SELECT source, title, publish_time FROM news WHERE source LIKE "%股吧%" ORDER BY publish_ts DESC LIMIT 10')
recent = cursor.fetchall()
print('\nRecent forum posts:')
for item in recent:
    print('  [{}] {}'.format(item[0], item[1][:50]))

conn.close()
