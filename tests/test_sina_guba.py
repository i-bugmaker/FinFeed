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
                
                print('\n=== Finding links ===')
                for a in soup.find_all("a", href=True)[:20]:
                    href = a["href"]
                    text = a.get_text(strip=True)[:50]
                    if text and len(text) > 5:
                        print('  {} - {}'.format(href[:60], text))
                        
                print('\n=== Finding list items ===')
                for item in soup.find_all(["li", "div"], class_=lambda x: x)[10:30]:
                    a_tag = item.find("a", href=True)
                    if a_tag:
                        href = a_tag["href"]
                        text = a_tag.get_text(strip=True)[:50]
                        if text and len(text) > 5:
                            print('  {} - {}'.format(href[:60], text))
            else:
                print('Content (first 800 chars):', response.text[:800])
        except Exception as e:
            print('Error:', e)

async def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://guba.sina.com.cn/",
    }
    
    sources = [
        ("新浪股吧", "http://guba.sina.com.cn/", headers),
        ("新浪股吧首页", "https://finance.sina.com.cn/stock/", headers),
        ("新浪股吧热门", "http://guba.sina.com.cn/?s=bar", headers),
        ("网易股吧", "https://guba.163.com/", headers),
        ("搜狐股吧", "https://guba.sohu.com/", headers),
    ]
    
    for name, url, h in sources:
        await test_source(name, url, h)

if __name__ == '__main__':
    asyncio.run(main())
