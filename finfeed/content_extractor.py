#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一正文提取器（按源定制 + 多通道 + 通用兜底）

针对 2026-09 全量排查发现的根因（一套通用密度算法硬啃所有站点），
本模块按「源」提供专属提取方案，并按需走不同数据通道：

1. 静态 HTML：用该源的专属正文容器选择器精确定位；
2. 内嵌 JSON：__NEXT_DATA__ / __NUXT__ / __INITIAL_STATE__ 里直接取正文；
3. 专用 API：源站提供 JSON 详情接口（华尔街见闻、格隆汇等）时优先走接口；
4. PDF：巨潮 / 上交所 / 深交所公告走 pypdf 文本抽取；
5. 通用兜底：专属方案全部落空时，退回密度打分算法（原 extract_readable_text）。

提取结果保留标题、发布时间、作者、正文段落与配图，统一编码，
剔除导航/广告/推荐/分享/页脚/版权等噪声；支持分页合并。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from bs4 import BeautifulSoup, Comment, NavigableString
from charset_normalizer import from_bytes as _cn_detect

logger = logging.getLogger("news_monitor")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
              "image/webp,*/*;q=0.8",
}
_TIMEOUT = httpx.Timeout(15.0)
_RE_CJK = re.compile(r"[\u4e00-\u9fff]")
_MIN_CJK = 10

# 段首即命中则整段剔除的尾部噪声（免责声明 / 责任编辑 / 版权 / 互动引导）
_TAIL_NOISE_RE = re.compile(
    r"^(?:\s*[（(【\[]?\s*)?(?:责任编辑|责\s*编|编辑[：:]|免责声明|版权声明|"
    r"版权归|未经授权|未经许可|本文仅代表|本(?:文|篇|网)(?:内容)?仅|"
    r"风险提示|股市有风险|入市需谨慎|投资(?:有|需)?风险|风险自担|"
    r"仅供参考|不代表|扫描二维码|扫码|关注(?:我们|公众号|微信)|"
    r"邮箱[：:]|联系(?:我们|邮箱)|转载(?:请联系|请注明)|"
    r"(?:媒体|合作)投稿|下载(?:APP|客户端)|打开APP|点击下载)",
    re.I,
)

# ── 噪声容器签名（专属容器内部再清一遍） ─────────────────────────
_NOISE_TAGS = [
    "script", "style", "noscript", "iframe", "nav", "header", "footer",
    "aside", "form", "button", "select", "textarea", "template", "svg",
    "canvas", "video", "audio",
]
_NOISE_RE = re.compile(
    r"comment|reply|share|qrcode|qr[-_]?code|social|advertis|sidebar|side[-_]bar|"
    r"breadcrumb|bread|pagination|pager|login|register|signin|signup|"
    r"copyright|friend|relate|recommend|hot[-_]?news|hot[-_]?list|ranking|rank|"
    r"toolbar|popup|modal|dialog|download|disclaimer|statement|notice|"
    r"tip|guide|tags?|label|crumb|menu|nav|footer|header",
    re.I,
)


@dataclass
class ExtractResult:
    """结构化正文提取结果"""
    title: str = ""
    publish_time: str = ""
    author: str = ""
    paragraphs: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    text: str = ""
    method: str = "none"  # html / next_data / nuxt / api / pdf / fallback

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "publish_time": self.publish_time,
            "author": self.author,
            "paragraphs": self.paragraphs,
            "images": self.images,
            "text": self.text,
            "method": self.method,
        }


# ── 源专属提取规则 ───────────────────────────────────────────────
# body:    正文容器 CSS 选择器（按优先级排列）
# title:   标题选择器
# time:    发布时间选择器
# author:  作者选择器
# img:     配图选择器（默认取正文容器内 <img>）
# encoding:强制编码（默认自动探测）
# api:     JSON 详情接口模板（{id} 为文章 id）
# api_id:  从 URL 提取 id 的正则
# js_data: 内嵌数据提取规则（见 _extract_embedded）
SOURCE_RULES: dict[str, dict[str, Any]] = {
    # ── 快讯模块 ─────────────────────────────────────────────
    "财联社": {
        "js": {"marker": "__NEXT_DATA__", "path": "props.pageProps.articleDetail.content"},
        "html": [".detail-content", "[class*='detail-content']"],
    },
    "同花顺": {
        "html": [".news-content-parsed", ".article-content", "[class*='news-content']"],
    },
    "东方财富": {
        "html": ["[id*='ContentBody']", "[id*='Content']", ".txtinfos", ".article-body"],
    },
    "雅虎财经": {"html": ["article", ".caas-body"]},  # 403 反爬，走兜底降级
    "21经济网": {
        "html": ["[class*='txtContent']", ".content", ".article-content"],
    },
    "金十数据": {"js": {"marker": "__NUXT__", "regex": r'content:"((?:[^"\\]|\\.)*)"'}},
    "格隆汇快讯": {
        "api": "https://www.gelonghui.com/api/news/{id}",
        "api_id": r"/news/(\d+)",
        "api_body": "content",
        "html": ["article.article-with-html", ".article-with-html"],
    },
    "法布财经": {"html": ["article", "[class*='article-content']"]},
    "企查查": {"html": ["[class*='post-detail']", "[class*='article']", ".detail-content"]},
    "每经网": {
        "html": [".g-article-left", "#ContentBody", ".article-content"],
        "title": [".g-article-title", "h1"],
        "time": [".g-article-time", ".time"],
    },
    "第一财经": {"html": [".m-on", ".content", "[class*='brief-content']"]},
    "中证快讯": {"html": ["article", ".content", ".artibody", "[class*='detail']"]},
    "上海证券报": {
        "js": {"marker": "__NEXT_DATA__", "path": "props.pageProps.data.textInfo.content"},
        "html": ["[class*='normalContentWrap']", "[class*='contentWrap']"],
    },
    "爱股票": {"html": [".live_detail_wrap", ".detail-content"]},
    "新华财经": {
        "html": [".xhcj_detail_main", ".xhcj_content"],
        "title": [".xhcj_detail_title", "h1"],
        "time": [".xhcj_time", ".time"],
        "pagination": r"(?P<base>.*?)(?:_\d+)?\.html$",
    },
    "金融界": {"html": [".article_content", ".article", "[class*='article-content']"]},
    "汇通网快讯": {"html": [".article-cont", ".article-main", "#article-cont"]},
    "新浪财经7×24": {
        "html": ["[class*='article-content']", "[class*='news-content']", ".main-content"],
    },
    "富途牛牛快讯": {"html": ["#newsDetail", ".newsDetail", "[class*='newsDetail']"]},
    "英为财情": {"html": ["article", ".articleBody", "[class*='article-content']"]},  # 403 反爬
    "火星财经": {"html": [".flash-details-wrapper", "[class*='detail-content']"]},
    # ── 财经模块 ─────────────────────────────────────────────
    "新浪财经": {
        "html": ["#artibody", ".article-content", "[class*='main-content']"],
        "title": ["h1"],
        "time": [".date", ".time-source"],
        "author": [".source", ".author"],
    },
    "同花顺原创": {"html": [".news-content-parsed", ".article-content", ".min-w-0"]},
    "同花顺财经": {"html": [".news-content-parsed", ".article-content"]},
    "华尔街见闻": {
        "api": "https://api-one.wallstcn.com/apiv1/content/articles/{id}?extract=0",
        "api_id": r"/(?:articles|news)/(\d+)",
        "api_body": "data.content",
    },
    "格隆汇文章": {
        "api": "https://www.gelonghui.com/api/news/{id}",
        "api_id": r"/news/(\d+)",
        "api_body": "content",
        "html": ["article.article-with-html", ".article-with-html"],
    },
    "巨潮公告": {"pdf": True},
    "cnBeta": {"html": [".article-summary", "article", ".news-content"]},
    "凤凰财经": {
        "html": ["article", "main", "[class*='artical']", "[class*='index_text']"],
        "title": ["h1"],
        "time": [".index_time", "[class*='time']"],
        "author": ["[class*='author']"],
    },
    "界面新闻": {
        "html": [".article-view", ".article-content", "[class*='article-main']"],
        "title": [".article-title", "h1"],
        "time": [".article-time", ".date"],
        "author": [".article-author", "[class*='author']"],
    },
    "澎湃新闻": {
        "js": {"marker": "__NEXT_DATA__",
               "path": "props.pageProps.detailData.contentDetail.content"},
        "html": ["[class*='cententWrap']", "[class*='contentWrap']", "main"],
    },
    "和讯网": {
        "html": [".art_contextBox", ".art_con", "#artibody"],
        "title": ["h1", ".art_title", ".title"],
        "encoding": "gb18030",
    },
    "财新网": {
        "html": ["#Main_Content_Val", "[id*='content']", ".article"],
        "title": [".title", "h1"],
        "time": [".time", "[class*='time']"],
    },
    "韭研公社": {"html": [".jc-home", "[class*='article-content']", "article"]},
    "萝卜投研": {"html": ["[class*='article']", "[class*='detail']", "main"]},
    "东方财富研报": {"html": ["[class*='report-content']", "[class*='article']"]},
    "港交所披露易": {"html": ["article", "main", ".news-content"]},
    "SEC EDGAR": {"html": ["article", ".formGrouping", "p"]},
    "上交所公告": {"pdf": True},
    "深交所公告": {"pdf": True},
}

# URL → 源名 快速映射（从 host + 路径特征反查，供 detail 接口使用）
_URL_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"cls\.cn"), "财联社"),
    (re.compile(r"yuanchuang\.10jqka\.com\.cn"), "同花顺原创"),
    (re.compile(r"10jqka\.com\.cn"), "同花顺"),
    (re.compile(r"eastmoney\.com"), "东方财富"),
    (re.compile(r"finance\.yahoo\.com"), "雅虎财经"),
    (re.compile(r"21jingji\.com"), "21经济网"),
    (re.compile(r"jin10\.com"), "金十数据"),
    (re.compile(r"gelonghui\.com"), "格隆汇文章"),
    (re.compile(r"fastbull\.cn"), "法布财经"),
    (re.compile(r"qcc\.com"), "企查查"),
    (re.compile(r"nbd\.com\.cn"), "每经网"),
    (re.compile(r"yicai\.com"), "第一财经"),
    (re.compile(r"cs\.com\.cn"), "中证快讯"),
    (re.compile(r"cnstock\.com"), "上海证券报"),
    (re.compile(r"aigupiao\.com"), "爱股票"),
    (re.compile(r"cnfin\.com"), "新华财经"),
    (re.compile(r"jrj\.com\.cn"), "金融界"),
    (re.compile(r"fx678\.com"), "汇通网快讯"),
    (re.compile(r"sina\.com\.cn/7x24"), "新浪财经7×24"),
    (re.compile(r"sina\.com\.cn"), "新浪财经"),
    (re.compile(r"futunn\.com"), "富途牛牛快讯"),
    (re.compile(r"investing\.com"), "英为财情"),
    (re.compile(r"marsbit\.co"), "火星财经"),
    (re.compile(r"wallstreetcn\.com"), "华尔街见闻"),
    (re.compile(r"cninfo\.com\.cn"), "巨潮公告"),
    (re.compile(r"cnbeta"), "cnBeta"),
    (re.compile(r"ifeng\.com"), "凤凰财经"),
    (re.compile(r"jiemian\.com"), "界面新闻"),
    (re.compile(r"thepaper\.cn"), "澎湃新闻"),
    (re.compile(r"hexun\.com"), "和讯网"),
    (re.compile(r"caixin\.com"), "财新网"),
    (re.compile(r"jiuyangongshe\.com"), "韭研公社"),
    (re.compile(r"datayes\.com"), "萝卜投研"),
    (re.compile(r"hkexnews\.hk"), "港交所披露易"),
    (re.compile(r"sec\.gov"), "SEC EDGAR"),
    (re.compile(r"sse\.com\.cn"), "上交所公告"),
    (re.compile(r"szse\.cn"), "深交所公告"),
]


def detect_source(url: str) -> str:
    """从 URL 推断源名（用于调用方未显式传 source 的场景）"""
    for pat, name in _URL_HINTS:
        if pat.search(url or ""):
            return name
    return ""


# ── 编码探测 ─────────────────────────────────────────────────────
def _detect_encoding(content: bytes, forced: str | None = None) -> str:
    if forced:
        return forced
    # 先看 BOM
    if content.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    # charset_normalizer 探测（GB2312/GBK 中文场景最可靠）
    try:
        best = _cn_detect(content).best()
        if best and best.encoding:
            return best.encoding
    except Exception:  # noqa: BLE001
        pass
    return "utf-8"


def _decode(content: bytes, forced: str | None = None) -> str:
    enc = _detect_encoding(content, forced)
    try:
        return content.decode(enc, errors="replace")
    except LookupError:
        return content.decode("utf-8", errors="replace")


# ── HTML 提取 ────────────────────────────────────────────────────
def _extract_embedded(html: str, rule: dict[str, Any]) -> str | None:
    """从内嵌 JSON（__NEXT_DATA__ / __NUXT__ / __INITIAL_STATE__）取正文"""
    marker = rule.get("marker", "")
    path = rule.get("path", "")
    regex = rule.get("regex", "")

    if marker and path:
        m = re.search(
            rf'<script[^>]+id="{re.escape(marker)}"[^>]*>(.*?)</script>',
            html, re.S,
        )
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            return None
        node: Any = data
        for key in path.split("."):
            if isinstance(node, dict):
                node = node.get(key)
            else:
                return None
            if node is None:
                return None
        return node if isinstance(node, str) else None

    if marker and regex:
        m = re.search(rf'window\.{re.escape(marker)}\s*=\s*', html)
        if not m:
            m = re.search(re.escape(marker) + r"\s*=\s*", html)
        if not m:
            return None
        # 在数据块内找 content 字段
        block = html[m.end():m.end() + 40000]
        cm = re.search(regex, block)
        if cm:
            return cm.group(1).replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")
    return None


def _clean_container(soup: BeautifulSoup) -> None:
    """剔除容器内的结构噪声，保留标题/时间/作者/段落/图片"""
    for tag in list(soup(_NOISE_TAGS)):
        try:
            tag.decompose()
        except Exception:  # noqa: BLE001
            pass
    # 注意：bs4 新版 find_all(attrs=True) 只返回最外层带属性标签，
    # 必须用 find_all(True) 遍历全部标签再过滤 attrs
    for tag in list(soup.find_all(True)):
        if not tag.attrs:
            continue
        ident = " ".join(tag.get("class") or []) + " " + (tag.get("id") or "")
        if _NOISE_RE.search(ident):
            try:
                tag.decompose()
            except Exception:  # noqa: BLE001
                pass


def _paragraphs_from_html(fragment: str) -> tuple[list[str], list[str]]:
    """把正文 HTML 片段转为 (段落列表, 配图列表)，保留段落结构"""
    soup = BeautifulSoup(fragment, "html.parser")
    _clean_container(soup)
    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if src and src.startswith(("http://", "https://")):
            images.append(src)

    paras: list[str] = []
    block_tags = ["p", "div", "section", "blockquote", "li", "h2", "h3", "td"]
    for blk in soup.find_all(block_tags):
        if blk.find(block_tags):  # 非叶子块 → 取直接裸露文本（如和讯网正文无 <p> 包裹）
            direct = " ".join(
                str(c).strip() for c in blk.children
                if isinstance(c, NavigableString) and not isinstance(c, Comment) and str(c).strip()
            )
            txt = " ".join(direct.split())
            if not txt:
                continue
        else:  # 叶子块 → 整块文本
            txt = " ".join(blk.get_text(" ", strip=True).split())
            if not txt:
                continue
        # 尾部噪声段落（免责声明/责任编辑/版权等）直接剔除
        if _TAIL_NOISE_RE.match(txt):
            continue
        cjk = len(_RE_CJK.findall(txt))
        if cjk < _MIN_CJK and len(txt) < 12:
            continue
        paras.append(txt)
    if not paras:  # 无块级结构 → 直接整体取文本
        txt = " ".join(soup.get_text(" ", strip=True).split())
        if txt and len(_RE_CJK.findall(txt)) >= _MIN_CJK:
            paras = [txt]
    return paras, images


def _extract_html(html: str, rule: dict[str, Any], title: str | None) -> ExtractResult:
    soup = BeautifulSoup(html, "lxml")
    _clean_container(soup)

    res = ExtractResult(method="html")
    # 标题 / 时间 / 作者（选中最匹配的选择器）
    for sel in rule.get("title", []):
        el = soup.select_one(sel)
        if el:
            t = " ".join(el.get_text(" ", strip=True).split())
            if t:
                res.title = t
                break
    for sel in rule.get("time", []):
        el = soup.select_one(sel)
        if el:
            t = " ".join(el.get_text(" ", strip=True).split())
            if t:
                res.publish_time = t
                break
    for sel in rule.get("author", []):
        el = soup.select_one(sel)
        if el:
            t = " ".join(el.get_text(" ", strip=True).split())
            if t:
                res.author = t
                break

    # 正文容器（按优先级逐一尝试）
    for sel in rule.get("html", []):
        nodes = soup.select(sel)
        if not nodes:
            continue
        # 取文本量最多的那个命中节点
        best_node = max(nodes, key=lambda n: len(_RE_CJK.findall(n.get_text(" ", strip=True))))
        paras, images = _paragraphs_from_html(str(best_node))
        cjk = sum(len(_RE_CJK.findall(p)) for p in paras)
        if cjk >= _MIN_CJK:
            res.paragraphs = paras
            res.images = images
            res.text = "\n".join(paras)
            if not res.title and title:
                res.title = title
            return res
    return res


# ── API 提取 ─────────────────────────────────────────────────────
async def _extract_api(client: httpx.AsyncClient, url: str, rule: dict[str, Any]) -> ExtractResult:
    res = ExtractResult(method="api")
    mid = re.search(rule["api_id"], url)
    if not mid:
        return res
    aid = mid.group(1)
    try:
        resp = await client.get(rule["api"].format(id=aid))
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.debug(f"API 提取失败 [{url}]: {e}")
        return res
    body = data
    for key in str(rule.get("api_body", "content")).split("."):
        if isinstance(body, dict):
            body = body.get(key)
        else:
            return res
        if body is None:
            return res
    if not isinstance(body, str) or not body.strip():
        return res
    paras, images = _paragraphs_from_html(body)
    cjk = sum(len(_RE_CJK.findall(p)) for p in paras)
    if cjk < _MIN_CJK:
        # 纯文本 fallback
        txt = body.strip()
        if len(_RE_CJK.findall(txt)) >= _MIN_CJK:
            paras = [ln for ln in re.split(r"\n+", txt) if ln.strip()]
    res.paragraphs = paras
    res.images = images
    res.text = "\n".join(paras)
    # 标题
    if isinstance(data, dict):
        for k in ("title", "Title"):
            if data.get(k):
                res.title = str(data[k])
                break
    return res


# ── PDF 提取 ─────────────────────────────────────────────────────
def _extract_pdf(content: bytes) -> ExtractResult:
    res = ExtractResult(method="pdf")
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as e:  # noqa: BLE001
        logger.debug(f"PDF 提取失败: {e}")
        return res
    paras = []
    for pg in pages:
        for ln in re.split(r"\n+", pg):
            ln = " ".join(ln.split())
            if not ln:
                continue
            cjk = len(_RE_CJK.findall(ln))
            if cjk < _MIN_CJK and len(ln) < 12:
                continue
            paras.append(ln)
    if sum(len(_RE_CJK.findall(p)) for p in paras) >= _MIN_CJK:
        res.paragraphs = paras
        res.text = "\n".join(paras)
    return res


# ── 上交所 acw_sc__v2 反爬求解（Node 执行源站 JS） ───────────────
import subprocess  # noqa: E402

_SSE_COOKIE_CACHE: dict[str, str] = {}
_SSE_COOKIE_TTL = 300  # 秒，cookie 有效期 1 小时，缓存 5 分钟足够


def _solve_sse_cookie(url: str) -> dict[str, str] | None:
    """抓取 SSE 反爬 JS 页面 → Node 执行其算法 → 返回 {acw_sc__v2: 值}"""
    import time
    now = time.time()
    if _SSE_COOKIE_CACHE and now - _SSE_COOKIE_CACHE.get("_t", 0) < _SSE_COOKIE_TTL:
        return {"acw_sc__v2": _SSE_COOKIE_CACHE["v"]}
    try:
        with httpx.Client(headers=_HEADERS, timeout=15.0,
                          follow_redirects=True) as c:
            h = c.get(url).text
        m = re.search(r"<script>(.*?)</script>", h, re.S)
        if not m or "acw_sc__v2" not in m.group(1):
            return None
        js = m.group(1)
        am = re.search(r"var arg1='([A-F0-9]+)'", js)
        algo = re.search(r"var _0x4818=function.*?document\.location\.reload\(\)",
                         js, re.S)
        if not am or not algo:
            return None
        node_js = (
            "var location={host:'static.sse.com.cn',reload:function(){}};\n"
            "var document={cookie:'',setcookie:function(){},location:location};\n"
            f"const arg1='{am.group(1)}';\n{algo.group(0)}\nconsole.log(document.cookie);\n"
        )
        p = subprocess.run(["node", "-e", node_js], capture_output=True,
                           text=True, timeout=20)
        vm = re.search(r"acw_sc__v2=([0-9a-f]+)", p.stdout or "")
        if vm:
            _SSE_COOKIE_CACHE["v"] = vm.group(1)
            _SSE_COOKIE_CACHE["_t"] = now
            return {"acw_sc__v2": vm.group(1)}
    except Exception as e:  # noqa: BLE001
        logger.debug(f"SSE 反爬求解失败: {e}")
    return None


def _get_sse_pdf(url: str) -> bytes | None:
    """带 acw_sc__v2 cookie 获取上交所 PDF，失败返回 None"""
    cookie = _solve_sse_cookie(url)
    headers = dict(_HEADERS)
    if cookie:
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookie.items())
    try:
        with httpx.Client(headers=headers, timeout=20.0,
                          follow_redirects=True) as c:
            r = c.get(url)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                return r.content
    except Exception as e:  # noqa: BLE001
        logger.debug(f"SSE PDF 获取失败 [{url}]: {e}")
    return None


# ── 通用兜底（复用原密度算法） ────────────────────────────────────
def _fallback_extract(html: str, title: str | None) -> ExtractResult:
    from finfeed.content_fetch import extract_readable_text
    text = extract_readable_text(html, title=title)
    res = ExtractResult(method="fallback")
    if text:
        res.text = text
        res.paragraphs = text.split("\n")
    if title:
        res.title = title
    return res


# ── 分页合并 ─────────────────────────────────────────────────────
def _pagination_urls(url: str, rule: dict[str, Any]) -> list[str]:
    """新华财经等 `xxx_1.html` 分页：返回 [url_2, url_3, ...] 的候选"""
    pat = rule.get("pagination")
    if not pat:
        return []
    m = re.match(pat, url)
    if not m:
        return []
    base = m.group("base")
    out = []
    for i in range(2, 6):  # 最多探测 5 页
        out.append(f"{base}_{i}.html")
    return out


# ── 主入口 ───────────────────────────────────────────────────────
async def fetch_article_detail(
    url: str,
    title: str | None = None,
    source: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> ExtractResult:
    """按 URL 抓取并提取结构化正文（多通道，按源定制）

    :param url: 文章详情页 URL
    :param title: 已知标题（列表页携带），用于兜底与去重
    :param source: 源名（优先于 URL 推断）
    :param client: 复用异步客户端（可选）
    """
    if not url or url == "#":
        return ExtractResult(method="none")
    src = source or detect_source(url)
    rule = SOURCE_RULES.get(src, {})
    if not rule:
        rule = {"html": ["article", "main", "[class*='content']"]}

    owns = client is None
    c = client or httpx.AsyncClient(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
    try:
        # 1) 专用 API 优先
        if rule.get("api"):
            res = await _extract_api(c, url, rule)
            if res.paragraphs:
                if not res.title and title:
                    res.title = title
                return res

        # 2) 抓页面
        resp = await c.get(url)
        resp.raise_for_status()
        content = resp.content
        enc = rule.get("encoding")
        html = _decode(content, enc)

        # 3) 内嵌 JSON
        if rule.get("js"):
            frag = _extract_embedded(html, rule["js"])
            if frag:
                paras, images = _paragraphs_from_html(frag)
                if sum(len(_RE_CJK.findall(p)) for p in paras) >= _MIN_CJK:
                    res = ExtractResult(method="js", paragraphs=paras, images=images,
                                        text="\n".join(paras))
                    if title:
                        res.title = title
                    return res

        # 4) PDF（含上交所 JS 反爬绕过）
        if rule.get("pdf") or resp.headers.get("content-type", "").startswith("application/pdf"):
            if rule.get("pdf") and b"<html" in content[:512]:
                # 上交所等 static.sse.com.cn 反爬：先解 cookie 再取 PDF
                pdf = _get_sse_pdf(url)
                if pdf:
                    return _extract_pdf(pdf)
            return _extract_pdf(content)

        # 5) 静态 HTML 专属选择器
        res = _extract_html(html, rule, title)
        if res.paragraphs:
            return res

        # 6) 分页合并（第一页无正文时尝试后续页，防止仅 _1 页有内容的情况）
        for purl in _pagination_urls(url, rule):
            try:
                presp = await c.get(purl)
                if presp.status_code != 200:
                    continue
                phtml = _decode(presp.content, enc)
                pres = _extract_html(phtml, rule, title)
                if pres.paragraphs:
                    return pres
            except Exception:  # noqa: BLE001
                continue

        # 7) 通用兜底
        return _fallback_extract(html, title)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"正文提取失败 [{url}] : {e}")
        return ExtractResult(method="none")
    finally:
        if owns:
            await c.aclose()


async def fetch_article_content(
    url: str,
    title: str | None = None,
    source: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """兼容入口：返回纯文本正文（失败返回空串）"""
    res = await fetch_article_detail(url, title=title, source=source, client=client)
    return res.text
