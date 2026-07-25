import asyncio
from core.parsers.forum_parsers import fetch_with_browser
from bs4 import BeautifulSoup

async def test_browser():
    url = "https://guba.eastmoney.com/list,600519.html"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://guba.eastmoney.com/",
        "Accept": "text/html",
    }
    
    try:
        print('Fetching with browser...')
        html = await fetch_with_browser(url, headers, timeout=45000)
        print('HTML length:', len(html) if html else 0)
        
        if html:
            soup = BeautifulSoup(html, "lxml")
            print('\n=== Finding all a tags ===')
            for a in soup.find_all("a", href=True)[:20]:
                href = a["href"]
                text = a.get_text(strip=True)[:40]
                print('  href={}, text={}'.format(href[:60], text))
            
            print('\n=== Finding by class articleh ===')
            for item in soup.find_all(class_="articleh")[:5]:
                print('  found')
                a_tag = item.find("a", href=True)
                if a_tag:
                    print('    href:', a_tag["href"])
                    print('    text:', a_tag.get_text(strip=True)[:50])
    except Exception as e:
        print('Error:', e)
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(test_browser())
