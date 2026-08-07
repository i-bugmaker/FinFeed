import sqlite3
from config.settings import DB_PATH

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute('SELECT DISTINCT source FROM news')
all_sources = cursor.fetchall()
print('All sources in database:')
for s in all_sources:
    cursor.execute('SELECT COUNT(*) FROM news WHERE source = ?', (s[0],))
    count = cursor.fetchone()[0]
    print('  {}: {} items'.format(s[0], count))

print('\n--- 检查新浪股吧数据 ---')
cursor.execute('SELECT title, url FROM news WHERE source = "新浪股吧" LIMIT 5')
rows = cursor.fetchall()
print('新浪股吧数据:', len(rows), 'items')
for row in rows:
    print('  ', row[0][:50])

print('\n--- 检查东方财富茅台股吧数据 ---')
cursor.execute('SELECT title, url FROM news WHERE source = "东方财富茅台股吧" LIMIT 5')
rows = cursor.fetchall()
print('东方财富茅台股吧数据:', len(rows), 'items')
for row in rows:
    print('  ', row[0][:50])

conn.close()
