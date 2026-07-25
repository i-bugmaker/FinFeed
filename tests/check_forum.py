import sqlite3
from config.settings import DB_PATH

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute('SELECT * FROM source_last_ts')
rows = cursor.fetchall()
print('source_last_ts table:')
for row in rows:
    print('  {}: ts={}'.format(row[0], row[1]))

cursor.execute('SELECT DISTINCT source FROM news WHERE source LIKE "%股吧%"')
sources = cursor.fetchall()
print('\nSources with 股吧 data:')
for s in sources:
    cursor.execute('SELECT COUNT(*) FROM news WHERE source = ?', (s[0],))
    count = cursor.fetchone()[0]
    print('  {}: {} items'.format(s[0], count))

conn.close()
