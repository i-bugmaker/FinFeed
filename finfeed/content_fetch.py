#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原文正文抓取与后台批量补齐

针对部分信息源（如凤凰财经、界面、澎湃、和讯等）在列表接口中未携带正文，
这里提供两个互补通道：

1. 按 URL 实时抓取文章正文（``fetch_article_content``），展开详情时随查随补；
2. 后台周期性任务（``content_backfill_loop``），批量补齐库里缺正文的记录。

抓到的正文统一写入 ``news.content`` 字段，支撑离线复盘。
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup, Comment, NavigableString

from finfeed.storage.database import (
    db_news_without_content,
    db_update_news_content,
)

logger = logging.getLogger("news_monitor")

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_TIMEOUT = httpx.Timeout(10.0)
# 每分钟后台最多补齐的条数，避免对来源站点造成压力
_BATCH_SIZE = 10
_BATCH_INTERVAL = 300  # 秒

_RE_BLANK_LINES = re.compile(r"[ \t\u3000]+")
_RE_EMPTY_LINES = re.compile(r"\n{3,}")
_RE_WS = re.compile(r"\s+")
_RE_CJK = re.compile(r"[\u4e00-\u9fff]")

# 少于该数量的中文字即判定为「未抓到正文」，宁可留空也不写入页面噪音
_MIN_CONTENT_CJK = 10

# ── 结构性噪声标签：整块移除 ───────────────────────────────────
_NOISE_TAGS = [
    "script", "style", "noscript", "iframe", "nav", "header", "footer",
    "aside", "form", "button", "select", "textarea", "template", "svg",
    "canvas", "video", "audio",
]

# ── 噪声容器签名：class / id 命中即整块移除 ─────────────────────
# 覆盖评论区、分享、二维码、侧栏、面包屑、分页、登录、版权、
# 相关推荐、排行榜、弹窗、下载引导等一切非正文区块。
_NOISE_CONTAINER_RE = re.compile(
    r"comment|reply|share|qrcode|qr[-_]?code|social|advertis|sidebar|side[-_]bar|"
    r"breadcrumb|bread|pagination|pager|login|register|signin|signup|"
    r"copyright|friend|relate|recommend|hot[-_]?news|hot[-_]?list|ranking|rank|"
    r"toolbar|popup|modal|dialog|download|disclaimer|statement|notice|"
    r"tip|guide|tags?|label|crumb|menu|nav",
    re.I,
)

# 标题容器单独处理：标题已由调用方持有，正文里不应重复出现，
# 顺带消除站点口号容器（如新浪 main-title）冒充正文的问题。
# 但长文本的 title 容器更可能是被误命名的正文，保留以免误删。
_TITLE_CONTAINER_RE = re.compile(r"title", re.I)
_TITLE_KEEP_MIN_LEN = 200

# ── 候选正文容器签名，分强/弱两级 ───────────────────────────────
# 强信号：正文专属命名（article-content / dtb-content / content-words …）。
# 弱信号：整页主容器（main / news / info），常裹着口号、侧栏与推荐位，
#        仅在强信号全部落空时才参与兜底，避免 main-title 这类栏目标题胜出。
_STRONG_HINT_RE = re.compile(r"article|content|detail|post|text|body|words|essay", re.I)
_WEAK_HINT_RE = re.compile(r"main|news|info", re.I)

# ── 样板行黑名单 ───────────────────────────────────────────────
# 页面 chrome 在不同站点 wording 不同，统一收敛为正则表，逐行过滤。
_BOILERPLATE_RES: list[re.Pattern[str]] = [
    re.compile(p, re.I)
    for p in (
        # 分享 / 扫码 / APP 下载引导
        r"打开(手机)?微信扫一扫", r"微信扫[一]?扫", r"扫码(下载|分享|关注|阅读)",
        r"扫描下载\s*APP", r"^下载\s*APP$", r"分享到\s*[:：]", r"^分享\s*[:：]",
        r"微信扫码分享", r"复制链接", r"立即前往", r"新浪财经APP",
        r"Android\s*版下载", r"iPhone\s*版下载", r"下载火星财经客户端",
        r"投资AI和Web3", r"聚焦AI和Web3",
        # 列表到底 / 翻页 / 展开
        r"已经到底了", r"^加载更多$", r"^查看更多$", r"^查看全部", r"^展开$", r"^收起$",
        # 面包屑与导航碎片
        r"首页\s*[>»]", r"^[>»\s]*首页\s*[>»]", r"[>»]\s*快讯\s*[>»]",
        r"^\s*首页\s+快讯(\s+快讯详情)?\s*$", r"^\s*首页\s+快讯详情\s*$",
        # 直播流刷新提示
        r"下一条快讯将在", r"秒后\s*到达", r"最先掌握财经",
        # 版权 / 备案 / 站点联系信息
        r"版权所有", r"Copyright", r"All\s+Rights\s+Reserved", r"ICP[备证]",
        r"客服热线", r"客服邮箱", r"商务合作", r"友情链接", r"联系我们",
        r"公司介绍", r"产品服务", r"广告招商", r"版权声明", r"合作伙伴",
        r"传播矩阵", r"未经授权", r"不得转载",
        # 登录 / 注册 / 人机验证
        r"其它方式登录", r"其他方式登录", r"微信登录", r"短信登录", r"忘记密码",
        r"获取验证码", r"^登\s*录$", r"^注\s*册$", r"登录\s*/\s*注册",
        r"注册/登录即代表", r"安全验证", r"拖动下方滑块", r"常规验证",
        r"^确定$", r"^取消$", r"^提交$",
        # 举报 / 投诉弹窗
        r"请选择投诉原因", r"举报成功", r"^举报$", r"^投诉$", r"^谣言$", r"^谩骂$",
        r"^色情低俗$", r"未成年人不良内容", r"欺诈或恶意营销",
        # 推荐位 / 排行 / 侧栏栏目标题
        r"^精彩推荐$", r"^相关推荐$", r"^最新要闻$", r"^热议$", r"^热门",
        r"^排行榜$", r"^更多$", r"猜你喜欢", r"推荐阅读", r"^事件播报$",
        r"^港股公告摘要$",
        # 内容状态与编辑信息
        r"^暂无详文$", r"^暂无内容$", r"^责任编辑", r"^阅读量", r"^免责声明",
        r"^风险提示", r"AI智能分析该文", r"该AI功能处于试用阶段",
        # 社交账号与联系方式
        r"TG\s*[:：]\s*@", r"微信(号|群)\s*[:：]", r"公众号",
        # 快讯站侧栏的情绪计数
        r"^利好\s*\d+$", r"^利空\s*\d+$",
        # 纯占位与脏数据
        r"^\?+\s*秒?$", r"^null$", r"^\s*TG\s*$",
    )
]

# 整行仅为日期/时间的「报头行」，如 2026-08-31、08月31日 22:41、2026-08-31 周一 22:41:53
_RE_DATELINE = re.compile(
    r"^\s*\d{1,4}\s*[年/.\-]\s*\d{1,2}\s*[月/.\-]\s*\d{1,2}\s*日?"
    r"[\s,，]*(周[一二三四五六日天]|星期[一二三四五六日天])?"
    r"[\s,，]*\d{0,2}\s*[:：]?\s*\d{0,2}\s*[:：]?\s*\d{0,2}\s*$"
)
# 「新华财经 | 2026年08月31日」这类站点署名报头
_RE_BYLINE_DATE = re.compile(
    r"^[^\s|｜]{0,12}\s*[|｜]\s*\d{4}\s*[年/.\-]\s*\d{1,2}\s*[月/.\-]\s*\d{1,2}"
)
_RE_WEEKDAY = re.compile(r"^周[一二三四五六日天]$|^星期[一二三四五六日天]$")


def _clean_text(text: str) -> str:
    """折叠空白、去除导航/脚本残留换行，压缩为紧凑段落文本"""
    text = text.replace("\u200b", "").replace("\xa0", " ")
    text = _RE_BLANK_LINES.sub(" ", text)
    text = _RE_EMPTY_LINES.sub("\n\n", text)
    return text.strip()


def _ident_of(tag) -> str:
    """拼接标签的 class 与 id，作为容器签名"""
    cls = tag.get("class")
    cls_s = " ".join(cls) if isinstance(cls, (list, tuple)) else (cls or "")
    return f"{cls_s} {tag.get('id') or ''}".strip()


def _strip_noise(soup: BeautifulSoup) -> None:
    """移除所有非正文结构：噪声标签 + 噪声容器"""
    for tag in list(soup(_NOISE_TAGS)):
        try:
            tag.decompose()
        except Exception:  # noqa: BLE001
            pass
    for tag in list(soup.find_all(attrs=True)):
        # 父节点被移除后，快照里的子节点 attrs 会变成 None
        if not tag.attrs:
            continue
        ident = _ident_of(tag)
        if not ident:
            continue
        if _NOISE_CONTAINER_RE.search(ident):
            try:
                tag.decompose()
            except Exception:  # noqa: BLE001
                pass
        elif _TITLE_CONTAINER_RE.search(ident):
            if len(tag.get_text(strip=True)) > _TITLE_KEEP_MIN_LEN:
                continue
            try:
                tag.decompose()
            except Exception:  # noqa: BLE001
                pass


def _is_boilerplate(line: str) -> bool:
    """判断一行是否为页面 chrome，而非正文"""
    s = line.strip()
    if not s:
        return True
    cjk = len(_RE_CJK.findall(s))
    # 无中文且非长段英文 → 视为导航/图标/数字碎片
    if cjk == 0 and len(s) < 40:
        return True
    # 中文极少且很短 → 报头碎片（如「08 月」「31」）
    if cjk < 3 and len(s) < 16:
        return True
    if _RE_WEEKDAY.match(s):
        return True
    for pat in _BOILERPLATE_RES:
        if pat.search(s):
            return True
    return False


def _is_dateline(line: str) -> bool:
    """整行仅为日期时间的报头行"""
    return bool(_RE_DATELINE.match(line) or _RE_BYLINE_DATE.match(line))


def _leaf_blocks(node) -> list:
    """返回 node 子树内不含块级子元素的文本块

    财经站正文常直挂在 div 上而无 <p>，故以「叶子块」而非 <p> 为单位取文本。
    """
    block_tags = ["p", "div", "blockquote", "section", "li", "td"]
    leaves = [
        el
        for el in node.find_all(block_tags)
        if not el.find(block_tags)
    ]
    return leaves or [node]


def _norm(s: str) -> str:
    r"""归一化：去掉空格与标点，保留中英文与数字（正则 \w 含汉字）"""
    return re.sub(r"[\s\W_]+", "", s)


def _extract_lines(node, title: str | None = None) -> list[str]:
    """把容器切分为行，剔除样板行与题名重复行

    题名重复行必须在打分前剔除：否则「仅含标题」的小容器（如 article_title）
    会以极高的纯度胜出，真正的正文容器反而落选。
    """
    norm_title = _norm(title) if title else ""
    lines: list[str] = []
    for blk in _leaf_blocks(node):
        for raw in blk.get_text("\n", strip=True).split("\n"):
            line = _RE_WS.sub(" ", raw).strip()
            if not line or _is_boilerplate(line) or _is_dateline(line):
                continue
            if norm_title:
                key = _norm(line)
                if key == norm_title or (len(key) >= 8 and key in norm_title):
                    continue
            lines.append(line)
    return lines


def _score_node(node, title: str | None = None) -> tuple[float, list[str]]:
    """为候选容器打「净得分」：有效正文 − 噪音 − 链接文本

    不采用「正文量 × 密度」的乘法模型 —— 乘法会持续奖励更大的容器，
    使整页包裹容器（正文 + 侧栏推荐 + 页脚）击败精确的正文容器。
    净得分模型下，容器每多裹一层无关文本就扣分，天然选出最贴合正文的那一个。

    返回 (得分, 过滤后的正文行)。无有效正文时返回 (-inf, [])。
    """
    lines = _extract_lines(node, title)
    if not lines:
        return float("-inf"), []

    cjk = len(_RE_CJK.findall("\n".join(lines)))
    if cjk < _MIN_CONTENT_CJK:
        return float("-inf"), []

    # 噪音 = 被过滤器剔除的字符数。此处不能用「总字符 − 中文字」：
    # 财经正文充满数字与代码（8428.8 万元、01802.HK、10 年期美债），
    # 那样会把正文自身的字符当成噪音扣分。
    kept = len(_RE_WS.sub("", "\n".join(lines)))
    total = len(_RE_WS.sub("", node.get_text(" ", strip=True)))
    noise = max(total - kept, 0)
    # 链接内文本：导航、相关推荐、排行榜几乎全部由链接构成
    link_cjk = sum(
        len(_RE_CJK.findall(a.get_text(strip=True))) for a in node.find_all("a")
    )
    return cjk - 1.5 * noise - 2.0 * link_cjk, lines


def _dedupe(lines: list[str]) -> list[str]:
    """去掉内容重复的行（同一段被多层容器重复包裹时会产生重复）"""
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = _norm(line)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def extract_readable_text(html: str, title: str | None = None) -> str:
    """从 HTML 提取可读正文文本（同步纯函数，便于单测）

    采用四步：噪声剔除 → 标题行剔除 → 候选容器净得分竞争 → 样板行过滤。
    不再依赖「首个命中的选择器」，避免把导航/分享/页脚当成正文。

    :param html: 原始 HTML
    :param title: 已知标题，用于剔除正题即全文的重复行（可选）
    :return: 正文文本；抓不到有效正文时返回空串（绝不返回页面 chrome）
    """
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")
    _strip_noise(soup)

    # 先用强信号容器竞争，全部落空时才退到整页主容器
    best_lines: list[str] = []
    for hint_re in (_STRONG_HINT_RE, _WEAK_HINT_RE):
        best_score, best_lines = float("-inf"), []
        for tag in soup.find_all(["article", "main", "div", "section"]):
            ident = _ident_of(tag)
            if not ident or not hint_re.search(ident):
                continue
            if not 20 <= len(tag.get_text(" ", strip=True)) <= 20000:
                continue
            score, lines = _score_node(tag, title)
            if score > best_score:
                best_score, best_lines = score, lines
        if best_lines:
            break

    if not best_lines:
        return ""

    lines = _dedupe(best_lines)
    if not lines:
        return ""

    text = _clean_text("\n".join(lines))
    # 最终闸门：去重后中文量不足，判定为未抓到正文
    return text if len(_RE_CJK.findall(text)) >= _MIN_CONTENT_CJK else ""


async def fetch_article_content(
    url: str,
    client: httpx.AsyncClient | None = None,
    title: str | None = None,
    source: str | None = None,
) -> str:
    """按 URL 抓取文章正文文本，失败或无正文返回空串

    自 2026-09 起委托 :mod:`finfeed.content_extractor` 的统一提取器：
    按源定制（专属选择器 / 内嵌 JSON / 专用 API / PDF），保留原有返回契约。
    """
    if not url or url == "#":
        return ""
    from finfeed.content_extractor import fetch_article_detail
    res = await fetch_article_detail(url, title=title, source=source, client=client)
    return res.text


async def backfill_content_batch(limit: int = _BATCH_SIZE, client: httpx.AsyncClient | None = None) -> int:
    """补齐一批缺失正文的记录，返回成功条数"""
    items = db_news_without_content(limit=limit)
    if not items:
        return 0
    owns = client is None
    c = client or httpx.AsyncClient(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
    filled = 0
    try:
        for i, n in enumerate(items):
            content = await fetch_article_content(
                n.url, c, title=getattr(n, "title", None),
                source=getattr(n, "source", None),
            )
            if content:
                db_update_news_content(n.id, content)
                filled += 1
            if i < len(items) - 1:
                await asyncio.sleep(1.0)
    finally:
        if owns:
            await c.aclose()
    if filled:
        logger.info(f"正文后台补齐：本次处理 {len(items)} 条，成功填充 {filled} 条")
    return filled


async def content_backfill_loop() -> None:
    """后台周期补齐正文（运行期间持续循环，退出后自行结束）"""
    async with httpx.AsyncClient(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True) as client:
        while True:
            try:
                await backfill_content_batch(client=client)
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.debug(f"正文后台补齐异常: {e}")
            try:
                await asyncio.sleep(_BATCH_INTERVAL)
            except asyncio.CancelledError:
                break