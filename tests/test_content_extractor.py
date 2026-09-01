#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：新浪 7×24 详情页正文提取不含推广位杂质。

对应线上问题：`/api/detail` 补抓正文时，「.article-content」命中了包裹
左右两栏的外层容器，右栏倒计时（下一条快讯将在 ?? 秒后到达新浪财经APP）、
口号（最先掌握财经7x24快讯）与日期报头行被当作正文落库。

样本取自 scripts/_probe_html/新浪财经7×24_0.html（真实详情页存档）。
"""
import os

from finfeed.content_extractor import (
    SOURCE_RULES,
    _extract_html,
    is_duplicate_of_meta,
)

_SAMPLE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "_probe_html", "新浪财经7×24_0.html",
)

_JUNK_KEYS = ("下一条快讯", "最先掌握", "到达新浪财经APP", "扫码下载", "09月01日")


def _extract_sample(title: str = "三环股份：累计回购733.97万股A股"):
    with open(_SAMPLE, encoding="utf-8", errors="replace") as f:
        html = f.read()
    return _extract_html(html, SOURCE_RULES["新浪财经7×24"], title)


def test_sina724_body_has_no_promo_junk():
    res = _extract_sample()
    assert res.paragraphs, "应能从 #artibody 提取到正文"
    for key in _JUNK_KEYS:
        assert key not in res.text, f"正文混入推广位/报头杂质: {key}"


def test_sina724_body_is_artibody_text():
    res = _extract_sample()
    assert "三环集团公告称" in res.text
    assert "累计回购成交总金额19.22亿元" in res.text


def test_tail_noise_and_dateline_filters():
    res = _extract_sample()
    # 即使正文容器退化为含右栏的外层容器（选择器兜底路径），
    # 段落过滤也必须剔除倒计时/口号/日期行
    from finfeed.content_extractor import _paragraphs_from_html
    dirty = (
        '<div class="article-content clearfix">'
        '<div class="news-date">09月01日 19:08</div>'
        '<div class="news-content"><div class="article">三环集团公告称累计回购A股股份733.97万股，占当前总股本的0.37%。</div></div>'
        '<div class="article-content-right"><div class="blk-countdown">'
        '<p>下一条快讯将在<span>??</span>秒后 到达新浪财经APP</p></div>'
        '<div class="blk-slogan"><span>最先掌握财经7x24快讯</span>'
        '<span>就在新浪财经APP</span></div></div></div>'
    )
    paras, _ = _paragraphs_from_html(dirty)
    assert paras == ["三环集团公告称累计回购A股股份733.97万股，占当前总股本的0.37%。"]


def test_is_duplicate_of_meta():
    title = "乌克兰副外长：基辅及其周边地区遭俄罗斯弹道导弹和无人机袭击，已致12人遇难。"
    # intro 为空时即使正文与标题相同也不算重复（落库以免前端显示「暂无正文」）
    assert not is_duplicate_of_meta(title, title, "")
    # intro 非空且正文 ⊆ 标题+摘要 → 重复，不落库（避免复读）
    assert is_duplicate_of_meta(title, title, "乌克兰外交部通报称救援仍在进行。")
    # 正文比标题+摘要更长（真实文章）→ 不算重复
    body = title + "乌克兰外交部表示，空袭发生在凌晨，多栋民用建筑受损，救援仍在进行。"
    assert not is_duplicate_of_meta(body, title, "乌克兰外交部通报称救援仍在进行。")
    # 空正文视为重复（宁可留空也不写噪声）
    assert is_duplicate_of_meta("", title, "乌克兰外交部通报称救援仍在进行。")
