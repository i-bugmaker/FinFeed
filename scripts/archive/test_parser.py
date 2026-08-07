import asyncio
import httpx
from config.sources import NewsSource
from core.parsers.forum_parsers import EastMoneyForumParser

async def test_forum_parser():
    sources = [
        NewsSource(
            name="东方财富热门股吧",
            url="https://guba.eastmoney.com/",
            parser_type="eastmoney_forum",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://guba.eastmoney.com/",
                "Accept": "text/html",
            },
        ),
        NewsSource(
            name="东方财富茅台股吧",
            url="https://guba.eastmoney.com/list,600519.html",
            parser_type="eastmoney_forum",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://guba.eastmoney.com/",
                "Accept": "text/html",
            },
        ),
    ]

    async with httpx.AsyncClient(timeout=30) as client:
        for src in sources:
            parser = EastMoneyForumParser(src)
            parser.last_ts = 0
            
            try:
                response = await client.get(src.url, headers=src.headers)
                print('=' * 60)
                print('Testing: {}'.format(src.name))
                print('URL: {}'.format(src.url))
                print('Status: {}'.format(response.status_code))
                
                news = await parser.parse(response)
                print('Parsed {} items'.format(len(news)))
                
                if news:
                    for item in news[:5]:
                        print('  - [{}] {}'.format(item.publish_time, item.title[:50]))
            except Exception as e:
                print('Error: {}'.format(e))

if __name__ == '__main__':
    asyncio.run(test_forum_parser())
