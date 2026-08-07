import asyncio
import httpx
from bs4 import BeautifulSoup

async def test_html():
    url = "https://guba.eastmoney.com/list,600519.html"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://guba.eastmoney.com/",
        "Accept": "text/html",
    }
    
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=headers)
        print('Status:', response.status_code)
        
        soup = BeautifulSoup(response.text, "lxml")
        
        print('\n=== Finding all a tags with href ===')
        for a in soup.find_all("a", href=True)[:30]:
            href = a["href"]
            text = a.get_text(strip=True)[:40]
            print('  href={}, text={}'.format(href[:60], text))
        
        print('\n=== Finding by class articleh ===')
        for item in soup.find_all(class_="articleh")[:10]:
            print('  class:', item.get("class"))
            a_tag = item.find("a", href=True)
            if a_tag:
                print('    href:', a_tag["href"])
                print('    text:', a_tag.get_text(strip=True)[:50])

if __name__ == '__main__':
    asyncio.run(test_html())
