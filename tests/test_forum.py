import urllib.request
import json

try:
    response = urllib.request.urlopen('http://localhost:8866/api/sentiment', timeout=10)
    data = json.loads(response.read().decode('utf-8'))
    
    print('Total news:', data.get('total', 0))
    print('Sources:', data.get('sources', []))
    
    sources_in_data = {}
    for news in data.get('news', []):
        src = news.get('source', '')
        sources_in_data[src] = sources_in_data.get(src, 0) + 1
    
    print('\nSources in API response:')
    for src, count in sorted(sources_in_data.items(), key=lambda x: -x[1]):
        print('  {}: {} items'.format(src, count))
        
except Exception as e:
    print('Error:', e)
