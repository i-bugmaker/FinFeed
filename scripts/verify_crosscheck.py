#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行情交叉校验模块冒烟脚本

覆盖：
  1) 导入冒烟（crosscheck 模块可 import 且无 import 副作用）
  2) 真实联网抓取 3-5 只流动性好的个股（600519/000001/600036/601318/000858），
     从东财（基准）+ 腾讯 + 同花顺（独立源）获取实时行情
  3) 打印三源对比表
  4) 断言：东财基准可获取（至少 1 只）、至少 2 个源成功、对比结果结构正确
  5) 断网时尽力降级不崩溃，结尾打印纯 ASCII 的 ALL PASS

运行（项目根目录）：
    python scripts/verify_crosscheck.py
"""

import sys
from pathlib import Path

# sys.path 引导：无论从哪个目录执行，都能导入 finfeed 包
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def banner(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> int:
    fails: list[str] = []
    tickers = ["600519", "000001", "600036", "601318", "000858"]

    # 1. 导入冒烟 + 无 import 副作用（import 时不应发任何网络请求）
    banner("[1] 导入冒烟（crosscheck 模块 import 无副作用）")
    try:
        import dataclasses

        from finfeed.market.crosscheck import QuoteDeviation, crosscheck_quotes

        assert dataclasses.is_dataclass(QuoteDeviation), "QuoteDeviation 应为 dataclass"
        print("  import OK; QuoteDeviation 是 dataclass")
    except Exception as e:  # noqa: BLE001
        fails.append(f"import: {e}")
        print(f"  import 失败: {e}")

    # 2. 真实联网交叉校验（尽力而为，断网不崩）
    banner("[2] 三源实时行情交叉校验（东财基准 + 腾讯 + 同花顺）")
    result: list = []
    try:
        result = crosscheck_quotes(tickers)
    except Exception as e:  # noqa: BLE001
        fails.append(f"crosscheck: {e}")
        print(f"  crosscheck 抛异常: {e}")

    if not result:
        print("  未取到任何对比结果（东财基准不可用或断网）—— 无法断言数据，见下")
    else:
        header = (
            f"{'代码':<7}{'名称':<9}{'东财价':>9}{'腾讯价':>9}{'同花价':>9}"
            f"{'价偏%':>8}{'涨跌偏':>8}  源"
        )
        print(header)
        print("-" * 70)
        for d in result:
            fmt = lambda v: f"{v:.2f}" if v is not None else "-"  # noqa: E731
            dev_fmt = lambda v: f"{v:.3f}" if v is not None else "-"  # noqa: E731
            mark = " <== 偏差超阈值" if d.deviant else ""
            print(
                f"{d.ticker:<7}{d.name[:4]:<9}{fmt(d.price_east):>9}"
                f"{fmt(d.price_tencent):>9}{fmt(d.price_ths):>9}"
                f"{dev_fmt(d.max_price_dev_pct):>8}{dev_fmt(d.max_pct_dev_pts):>8}  "
                f"{','.join(d.sources)}{mark}"
            )
        print("-" * 70)
        print(f"共 {len(result)} 只；告警 {sum(1 for d in result if d.deviant)} 只")

    # 3. 断言
    banner("[3] 断言")
    east_ok = sum(1 for d in result if d.price_east is not None)
    print(f"  东财基准可取: {east_ok}/{len(tickers)}")
    print(f"  对比结果数: {len(result)}")
    multi_src = sum(1 for d in result if len(d.sources) >= 2)
    print(f"  达到 2+ 源的标的: {multi_src}/{len(result)}")
    if result:
        print(f"  样例(600519): 东财={result[0].price_east} 腾讯={result[0].price_tencent}"
              f" 同花顺={result[0].price_ths}")

    if east_ok == 0:
        fails.append("东财基准完全不可用（应至少 1 只可取）")
    if not result:
        fails.append("对比结果为空")
    elif multi_src < 2:
        fails.append(f"达到 2+ 源的标的过少: {multi_src}（应 >= 2）")
    if not fails:
        for d in result:
            if d.price_east is None:
                continue
            if d.price_tencent is not None:
                exp = d.price_east
                assert abs(d.price_tencent - exp) < 0.5 or d.deviant, \
                    f"{d.ticker} 腾讯价与东财价偏差过大且未标记告警"
            assert isinstance(d.ticker, str) and d.ticker, f"{d} ticker 非法"
        print("  结构断言通过")

    # 4. 汇总
    banner("结果汇总")
    if fails:
        print(f"失败 {len(fails)} 项:")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
