import urllib.request
import json

try:
    response = urllib.request.urlopen("http://localhost:8866/api/sentiment")
    data = json.loads(response.read().decode("utf-8"))
    
    print("舆情API响应:")
    print("  总条数:", data.get("total", 0))
    print("  源列表:", data.get("sources", []))
    
    if data.get("news"):
        print("\n  最新舆情:")
        for item in data["news"][:10]:
            print('    [{}] {} - {}'.format(item.get("source", ""), item.get("publish_time", ""), item.get("title", "")[:50]))
except Exception as e:
    print("请求失败:", e)
