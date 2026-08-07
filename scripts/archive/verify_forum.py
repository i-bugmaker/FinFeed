from config.sources import get_forum_sources

forum_source_names = [s.name for s in get_forum_sources()]
print('论坛源名称:', forum_source_names)

import sqlite3
from config.settings import DB_PATH
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("SELECT DISTINCT source FROM news WHERE source LIKE '%股吧%'")
rows = cursor.fetchall()
print('数据库中股吧源:', [r[0] for r in rows])

cursor.execute("SELECT COUNT(*) FROM news WHERE source = '新浪股吧'")
count = cursor.fetchone()[0]
print('新浪股吧数据条数:', count)

cursor.execute("SELECT COUNT(*) FROM news WHERE source = '东方财富茅台股吧'")
count = cursor.fetchone()[0]
print('东方财富茅台股吧数据条数:', count)

conn.close()
