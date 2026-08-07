import asyncio
import httpx
from config.sources import NewsSource
from core.parsers.forum_parsers import SinaStockBarParser

async def test_forum_parser():
    source = NewsSource(
        name="新浪股吧",
        url="http://guba.sina.com.cn/",
        parser_type="sina_stock_bar",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "http://guba.sina.com.cn/",
            "Accept": "text/html",
        },
    )

    async with httpx.AsyncClient(timeout=30) as client:
        parser = SinaStockBarParser(source)
        parser.last_ts = 0
        
        try:
            response = await client.get(source.url, headers=source.headers)
            print('=' * 60)
            print('Testing: {}'.format(source.name))
            print('URL: {}'.format(source.url))
            print('Status: {}'.format(response.status_code))
            
            news = await parser.parse(response)
            print('Parsed {} items'.format(len(news)))
            
            if news:
                for item in news[:10]:
                    print('  - [{}] {}'.format(item.publish_time, item.title[:60]))
        except Exception as e:
            print('Error: {}'.format(e))
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(test_forum_parser())
