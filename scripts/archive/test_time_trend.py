import sqlite3
import os
from config.settings import DB_PATH

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("=== 测试时间趋势查询 ===")
day_ago = int(__import__('time').time()) - 86400
c.execute("""
    SELECT strftime('%m-%d %H:00', publish_ts, 'unixepoch', 'localtime') as hour_bucket,
           COUNT(*) as cnt
    FROM news WHERE publish_ts >= ?
    GROUP BY hour_bucket ORDER BY hour_bucket LIMIT 10
""", (day_ago,))
rows = c.fetchall()
for r in rows:
    print(f"time='{r['hour_bucket']}', count={r['cnt']}")

print("\n=== 检查 publish_ts 样本 ===")
c.execute("SELECT id, publish_ts, publish_time FROM news WHERE publish_ts > 0 LIMIT 5")
for r in c.fetchall():
    print(f"id={r['id']}, ts={r['publish_ts']}, time={r['publish_time']}")

conn.close()
