import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from finfeed.f10.renderers.terminal import C
from finfeed.f10.ths_config import (
    _BROWSER_HEADERS,
    _COOLDOWN,
    _MAX_FAILS,
    _UA_POOL,
    F10_REFERER,
    MAX_CONCURRENT_REQUESTS,
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_MIN,
    SESSION,
    _circuits,
    _soup_cache,
)
from finfeed.f10.utils.logger import vlog

_bs4_available = None


def _get_bs4():
    global _bs4_available
    if _bs4_available is None:
        try:
            from bs4 import BeautifulSoup
            _bs4_available = BeautifulSoup
        except ImportError:
            sys.exit("缺少依赖: 请先运行  pip install requests beautifulsoup4")
    return _bs4_available


class HttpClient:
    def __init__(self):
        self._circuits = _circuits
        self._soup_cache = _soup_cache
        self._session = SESSION
        self._ua_pool = _UA_POOL
        self._browser_headers = _BROWSER_HEADERS
        self._max_fails = _MAX_FAILS
        self._cooldown = _COOLDOWN

    def _extract_domain(self, url):
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc or "default"

    def _get_circuit(self, domain):
        if domain not in self._circuits:
            self._circuits[domain] = {"fail_count": 0, "open_until": 0.0}
        return self._circuits[domain]

    def _rotate_ua(self):
        ua = random.choice(self._ua_pool)
        self._session.headers.update({"User-Agent": ua})
        return ua

    def safe_get(self, url, *, params=None, headers=None, timeout=20,
                 min_delay=None, max_delay=None, _retries=3):
        if min_delay is None:
            min_delay = REQUEST_DELAY_MIN
        if max_delay is None:
            max_delay = REQUEST_DELAY_MAX
        domain = self._extract_domain(url)
        circuit = self._get_circuit(domain)
        now = time.time()
        if circuit["open_until"] > now:
            wait = circuit["open_until"] - now
            print(f"{C.RED}[熔断][{domain}] 请求过于频繁, 暂停 {wait:.0f} 秒…{C.R}")
            time.sleep(wait)
            circuit["open_until"] = 0.0
            circuit["fail_count"] = 0

        time.sleep(random.uniform(min_delay, max_delay))

        self._rotate_ua()

        merged = dict(self._browser_headers)
        if headers:
            merged.update(headers)

        for attempt in range(_retries):
            try:
                r = self._session.get(url, params=params, headers=merged, timeout=timeout)

                if r.status_code == 200:
                    circuit["fail_count"] = 0
                    ct = r.headers.get("Content-Type", "")
                    if "text/html" in ct:
                        body_preview = r.text[:500].lower()
                        if ("验证码" in body_preview
                                or "captcha" in body_preview
                                or "请完成安全验证" in body_preview
                                or "访问过于频繁" in body_preview
                                or "请稍后重试" in body_preview):
                            print(f"{C.YEL}[警告] 检测到验证码/拦截页, "
                                  f"等待 10 秒后重试…{C.R}")
                            time.sleep(10)
                            self._rotate_ua()
                            continue
                    return r

                if r.status_code in (403, 429, 503):
                    backoff = min(5 * (2 ** attempt), 60)
                    print(f"{C.YEL}[限流] HTTP {r.status_code}, "
                          f"等待 {backoff}s 后重试 ({attempt+1}/{_retries})…{C.R}")
                    time.sleep(backoff)
                    self._rotate_ua()
                    continue

                circuit["fail_count"] = 0
                return r

            except __import__("requests").exceptions.RequestException as e:
                backoff = min(3 * (2 ** attempt), 30)
                print(f"{C.YEL}[网络异常] {e}, "
                      f"等待 {backoff}s 后重试 ({attempt+1}/{_retries})…{C.R}")
                time.sleep(backoff)

        circuit["fail_count"] += 1
        if circuit["fail_count"] >= self._max_fails:
            circuit["open_until"] = time.time() + self._cooldown
            print(f"{C.RED}[熔断][{domain}] 连续 {self._max_fails} 次请求失败, "
                  f"暂停 {self._cooldown:.0f} 秒。{C.R}")

        class _ErrResp:
            status_code = 0
            ok = False
            text = ""
            content = b""
            def json(self):
                raise ValueError("request failed (all retries exhausted)")
        return _ErrResp()

    def safe_get_multi(self, urls, *, params=None, headers=None, timeout=20,
                       min_delay=None, max_delay=None, max_workers=None):
        if max_workers is None:
            max_workers = MAX_CONCURRENT_REQUESTS
        results = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {
                executor.submit(
                    self.safe_get, url, params=params, headers=headers,
                    timeout=timeout, min_delay=min_delay, max_delay=max_delay
                ): url
                for url in urls
            }
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    results[url] = future.result()
                except Exception as e:
                    # e 必须在默认参数里固化：except 块结束后绑定即被删除，
                    # 延迟到 .json() 再引用会抛 NameError
                    class _ErrResp:
                        status_code = 0
                        ok = False
                        text = ""
                        content = b""
                        def json(self, _e=e):
                            raise ValueError(f"request failed: {_e}")
                    results[url] = _ErrResp()
        return results

    def _get_soup(self, url, referer="https://basic.10jqka.com.cn/", encoding="gbk"):
        cache_key = url
        if cache_key in self._soup_cache:
            return self._soup_cache[cache_key]
        try:
            r = self.safe_get(url, headers={"Referer": referer}, timeout=20)
            if r.status_code != 200:
                # 失败结果不写入缓存：否则一次网络抖动会让该 URL
                # 在整个进程生命周期内永远返回 None
                vlog(f"_get_soup HTTP {r.status_code}: {url}")
                return None
            html = r.content.decode(encoding, "ignore")
            BeautifulSoup = _get_bs4()
            soup = BeautifulSoup(html, "html.parser")
            self._soup_cache[cache_key] = soup
            return soup
        except Exception as e:
            vlog(f"_get_soup 异常: {url}: {e}")
            return None

    def _ths_api(self, prefix, path, params):
        url = f"https://basic.10jqka.com.cn/{prefix}/{path}"
        try:
            r = self.safe_get(url, params=params,
                              headers={"Referer": F10_REFERER}, timeout=20)
            return r.json()
        except Exception as e:
            print(f"{C.DIM}[API异常] {prefix}/{path}: {e}{C.R}",
                  file=sys.stderr)
            return {"status_code": -1, "error": str(e)}


def api_failed(data):
    """判断 _ths_api 的返回是否为失败伪 dict（接口挂掉而非空数据）。"""
    return (not isinstance(data, dict)
            or data.get("status_code") == -1
            or data.get("status_code") == 0)


_client = HttpClient()


def safe_get(url, *, params=None, headers=None, timeout=20,
             min_delay=None, max_delay=None, _retries=3):
    return _client.safe_get(
        url, params=params, headers=headers, timeout=timeout,
        min_delay=min_delay, max_delay=max_delay, _retries=_retries
    )


def safe_get_multi(urls, *, params=None, headers=None, timeout=20,
                   min_delay=None, max_delay=None, max_workers=None):
    return _client.safe_get_multi(
        urls, params=params, headers=headers, timeout=timeout,
        min_delay=min_delay, max_delay=max_delay, max_workers=max_workers
    )


def _get_soup(url, referer="https://basic.10jqka.com.cn/", encoding="gbk"):
    return _client._get_soup(url, referer=referer, encoding=encoding)


def _ths_api(prefix, path, params):
    return _client._ths_api(prefix, path, params)
