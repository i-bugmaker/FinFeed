import sqlite3
from config.settings import DB_PATH

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute('SELECT url, title FROM news WHERE source = "东方财富股吧" LIMIT 10')
rows = cursor.fetchall()
print('Existing 东方财富股吧 data:')
for row in rows:
    print('  URL:', row[0][:80])
    print('  Title:', row[1][:60])
    print()

conn.close()
