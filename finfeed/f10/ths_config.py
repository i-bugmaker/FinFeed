"""抓取引擎配置模块。

包含版本号、User-Agent 池、请求会话、请求延迟、股票过滤规则等全局配置。

重要常量:
    __version__: 版本号
    SESSION: requests.Session 代理对象（延迟初始化）
    REQUEST_DELAY_MIN/MAX: 每次请求前的随机延迟范围（反爬限速）
    DISPLAY_LIMIT: 各模块列表/记录的默认显示条数上限
"""

import random

__version__ = "1.2.0"


_UA_POOL = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) "
     "Gecko/20100101 Firefox/138.0"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"),
]

_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
}

_SESSION = None


def _get_session():
    global _SESSION
    if _SESSION is None:
        try:
            import requests
        except ImportError:
            import sys
            sys.exit("缺少依赖: 请先运行  pip install requests beautifulsoup4")
        _SESSION = requests.Session()
        _SESSION.headers.update(_BROWSER_HEADERS)
        _SESSION.headers.update({"User-Agent": random.choice(_UA_POOL)})
    return _SESSION


class _SessionProxy:
    def __getattr__(self, name):
        return getattr(_get_session(), name)

    def __setattr__(self, name, value):
        setattr(_get_session(), name, value)


SESSION = _SessionProxy()

F10_REFERER = "https://basic.10jqka.com.cn/astockpc/astockmain/index.html"

_circuits = {}
_MAX_FAILS = 6
_COOLDOWN = 30.0

REQUEST_DELAY_MIN = 0.5
REQUEST_DELAY_MAX = 1.0

MAX_CONCURRENT_REQUESTS = 3

# 各模块列表/记录的默认显示条数上限（config.json 的 display_limit 覆盖）
DISPLAY_LIMIT = 30

_soup_cache = {}


_INVALID_PREFIXES = ('PT', '退市')
_INVALID_KEYWORDS = ('基金', '债券', '权证', '可转债', 'ETF', 'LOF', 'QDII')
_VALID_CODE_PREFIXES = ('600','601','603','605',
                        '000','001','002','003',
                        '300','301','688')
