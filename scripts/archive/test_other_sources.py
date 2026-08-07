import asyncio
import httpx
from bs4 import BeautifulSoup

async def test_source(name, url, headers):
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(url, headers=headers)
            print('=' * 60)
            print('Testing:', name)
            print('URL:', url)
            print('Status:', response.status_code)
            print('Content length:', len(response.text))
            
            if response.status_code == 200 and len(response.text) > 1000:
                soup = BeautifulSoup(response.text, "lxml")
                a_tags = soup.find_all("a", href=True)
                print('Found {} a tags'.format(len(a_tags)))
                
                if len(a_tags) > 0:
                    print('Sample links:')
                    for a in a_tags[:10]:
                        href = a["href"]
                        text = a.get_text(strip=True)[:40]
                        if text:
                            print('  {} - {}'.format(href[:50], text))
            else:
                print('Content (first 500 chars):', response.text[:500])
        except Exception as e:
            print('Error:', e)

async def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    
    sources = [
        ("雪球热门", "https://xueqiu.com/", headers),
        ("雪球讨论", "https://xueqiu.com/snowball", headers),
        ("淘股吧", "https://www.taoguba.com.cn/", headers),
        ("同花顺股吧", "https://guba.10jqka.com.cn/", headers),
        ("股吧网", "https://www.gubaba.com/", headers),
    ]
    
    for name, url, h in sources:
        await test_source(name, url, h)

if __name__ == '__main__':
    asyncio.run(main())
