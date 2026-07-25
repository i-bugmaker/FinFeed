import asyncio
import httpx
import json

async def test_mobile_api():
    api_urls = [
        "https://guba.eastmoney.com/list,600519.html",
        "https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=20&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23&fields=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152",
        "https://guba.eastmoney.com/api/topic/list?pageSize=20&pageIndex=1&sort=1",
        "https://guba.eastmoney.com/api/topic/list?code=600519&pageSize=20&pageIndex=1",
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://guba.eastmoney.com/",
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        for url in api_urls:
            try:
                response = await client.get(url, headers=headers)
                print('=' * 60)
                print('URL:', url)
                print('Status:', response.status_code)
                print('Content-Type:', response.headers.get('content-type', ''))
                print('Content length:', len(response.text))
                print('First 800 chars:', response.text[:800])
            except Exception as e:
                print('Error:', e)

if __name__ == '__main__':
    asyncio.run(test_mobile_api())
