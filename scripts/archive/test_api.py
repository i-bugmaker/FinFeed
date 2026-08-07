import asyncio
import httpx
import json

async def test_api():
    api_url = "https://guba.eastmoney.com/list,600519,f.html"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://guba.eastmoney.com/",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(api_url, headers=headers)
            print('Status:', response.status_code)
            print('Content-Type:', response.headers.get('content-type', ''))
            print('Content length:', len(response.text))
            print('First 500 chars:', response.text[:500])
        except Exception as e:
            print('Error:', e)

if __name__ == '__main__':
    asyncio.run(test_api())
