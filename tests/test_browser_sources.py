import asyncio
from core.parsers.forum_parsers import fetch_with_browser
from bs4 import BeautifulSoup

async def test_source(name, url, headers):
    try:
        print('=' * 60)
        print('Testing:', name)
        print('URL:', url)
        
        html = await fetch_with_browser(url, headers, timeout=45000)
        print('HTML length:', len(html) if html else 0)
        
        if html and len(html) > 5000:
            soup = BeautifulSoup(html, "lxml")
            
            print('\n=== Finding article items ===')
            for item in soup.find_all(class_=lambda x: x and any(k in str(x) for k in ["article", "post", "item", "list", "topic"]))[:10]:
                a_tag = item.find("a", href=True)
                if a_tag:
                    href = a_tag["href"]
                    text = a_tag.get_text(strip=True)[:50]
                    if text and len(text) > 5:
                        print('  {} - {}'.format(href[:60], text))
                        
            print('\n=== Finding by tag ===')
            for item in soup.find_all(["article", "div", "li"], class_=lambda x: x)[10:20]:
                a_tag = item.find("a", href=True)
                if a_tag:
                    href = a_tag["href"]
                    text = a_tag.get_text(strip=True)[:50]
                    if text and len(text) > 5:
                        print('  {} - {}'.format(href[:60], text))
        elif html:
            print('Content (first 1000 chars):', html[:1000])
    except Exception as e:
        print('Error:', e)
        import traceback
        traceback.print_exc()

async def main():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    
    sources = [
        ("同花顺论坛", "http://forum.10jqka.com.cn/", headers),
        ("东方财富股吧热门", "https://guba.eastmoney.com/", headers),
        ("雪球", "https://xueqiu.com/", headers),
    ]
    
    for name, url, h in sources:
        await test_source(name, url, h)

if __name__ == '__main__':
    asyncio.run(main())
