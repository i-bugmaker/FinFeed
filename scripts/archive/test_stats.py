import sys
sys.path.insert(0, '.')
from storage.database import get_db_manager
import json

db = get_db_manager()
stats = db.get_statistics()
print("=== time_trend (前10条) ===")
for item in stats['time_trend'][:10]:
    print(item)
print(f"\nTotal time buckets: {len(stats['time_trend'])}")
print(f"\n=== importance_distribution ===")
print(json.dumps(stats['importance_distribution'], ensure_ascii=False, indent=2))
