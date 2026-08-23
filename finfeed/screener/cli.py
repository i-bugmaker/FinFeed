#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股模块命令行入口。

用法（通过主程序 main.py 转发）：
    python main.py --screener run                       # 实时拉取 easy-tdx 并评分
    python main.py --screener run --load-csv snap.csv   # 离线回放已存快照
    python main.py --screener run --no-technical        # 关闭 K 线富化
    python main.py --screener run -o report.md --json-out res.json
    python main.py --screener explain                   # 仅打印方法论

也可独立运行：python -m finfeed.screener run
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
from typing import Any

from . import datasource, report as report_mod, scoring
from .config import load_config
from .models import ScreenerResult

logger = logging.getLogger("finfeed.screener.cli")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """把选股相关参数挂到主 parser（与现有 --market 等同级）。"""
    parser.add_argument(
        "--screener", metavar="ACTION",
        choices=["run", "explain", "backtest", "backtest-snapshots"],
        help="选股模块: run(实时/离线回放评分) / explain(仅输出方法论) / "
             "backtest(K线重建因子回测) / backtest-snapshots(快照库真实因子回测)",
    )
    parser.add_argument("--load-csv", help="从 CSV 快照离线回放（由 --save-csv 生成）")
    parser.add_argument("--save-csv", help="将实时行情快照保存为 CSV（便于离线回放）")
    parser.add_argument("--no-technical", action="store_true", help="关闭 K 线技术面富化")
    parser.add_argument("--top", type=int, default=40, help="报告展示 Top N（默认 40）")
    parser.add_argument("--top-tech", type=int, default=200, help="技术面富化前 N 只候选（默认 200）")
    parser.add_argument("--report", help="Markdown 报告输出路径（默认 ./screener_report.md）")
    parser.add_argument("--json-out", help="JSON 结果输出路径（默认 ./screener_result.json）")
    parser.add_argument("--config", help="自定义评分配置 JSON 路径（覆盖默认权重/阈值）")
    parser.add_argument("--no-save", action="store_true", help="不写文件，仅控制台打印摘要")
    # ---- backtest 参数 ----
    parser.add_argument("--pool-size", type=int, default=200, help="回测股票池规模（默认 200）")
    parser.add_argument("--cross-sections", type=int, default=8, help="回测截面数量（默认 8）")
    parser.add_argument("--step", type=int, default=5, help="截面间隔交易日（默认 5）")
    parser.add_argument("--horizon", type=int, default=20, help="最长前瞻收益天数（默认 20）")
    parser.add_argument("--sensitivity", action="store_true", help="回测附带权重敏感性扫描（正负 20pct 扰动）")


def _print_summary(result: ScreenerResult, top_n: int) -> None:
    print("\n" + "=" * 72)
    print(f"选股评分完成 | 数据源: {result.data_source} | 技术面: "
          f"{'启用' if result.technical_enabled else '未启用'}")
    print(f"全市场 {result.universe_size} → 通过过滤 {result.screened_size} → "
          f"评分 {result.scored_size} 只")
    strong = [s for s in result.scores if s.tier == "strong"]
    print(f"入选候选(Strong): {len(strong)} 只")
    print("-" * 72)
    print(f"{'排名':>4} {'代码':<8} {'名称':<10} {'价':>8} {'涨跌%':>7} "
          f"{'PE':>7} {'综合':>6} {'资金':>5} {'动量':>5} {'估值':>5} {'量价':>5} {'质量':>5} {'情绪':>5} {'评级':<8}")
    for i, s in enumerate(result.scores[:top_n], 1):
        tier = {"strong": "入选", "watch": "关注", "observe": "观察", "none": "—"}.get(s.tier, s.tier)
        print(f"{i:>4} {s.code:<8} {s.name:<10} {s.price:>8.2f} {s.change_pct:>+7.2f} "
              f"{s.pe_ttm:>7.1f} {s.total_score:>6.1f} {s.capital_score:>5.0f} "
              f"{s.momentum_score:>5.0f} {s.valuation_score:>5.0f} {s.liquidity_score:>5.0f} "
              f"{s.quality_score:>5.0f} {s.sentiment_score:>5.0f} {tier:<8}")
    print("=" * 72)


def _default_path(name: str) -> str:
    return os.path.join(os.getcwd(), name)


def cmd_screener(args: argparse.Namespace) -> int:
    """执行选股命令，返回进程退出码。"""
    cfg = load_config(getattr(args, "config", None))

    # ---- explain ----
    if args.screener == "explain":
        text = cfg.explain()
        print(text)
        if getattr(args, "report", None):
            with open(args.report, "w", encoding="utf-8") as fp:
                fp.write(text)
            print(f"\n方法论已写入: {args.report}")
        return 0

    # ---- backtest ----
    if args.screener in ("backtest", "backtest-snapshots"):
        from . import backtest as backtest_mod

        if args.screener == "backtest-snapshots":
            result = backtest_mod.run_backtest_from_snapshots(
                pool_size=getattr(args, "pool_size", 200),
                n_cross=getattr(args, "cross_sections", 8),
                step=getattr(args, "step", 5),
                max_horizon=getattr(args, "horizon", 20),
            )
        else:
            result = backtest_mod.run_backtest(
                pool_size=getattr(args, "pool_size", 200),
                n_cross=getattr(args, "cross_sections", 8),
                step=getattr(args, "step", 5),
                max_horizon=getattr(args, "horizon", 20),
            )
        text = backtest_mod.render_markdown(result)
        print(text)
        out = getattr(args, "report", None) or _default_path("screener_backtest.md")
        with open(out, "w", encoding="utf-8") as fp:
            fp.write(text)
        print(f"\n回测报告已写出: {out}")

        # 权重敏感性扫描（--sensitivity）
        if getattr(args, "sensitivity", False) and args.screener == "backtest":
            sens = backtest_mod.weight_sensitivity(
                pool_size=getattr(args, "pool_size", 200),
                n_cross=max(3, min(getattr(args, "cross_sections", 8), 6)),
                step=getattr(args, "step", 5),
                max_horizon=getattr(args, "horizon", 20),
            )
            sens_text = backtest_mod.render_sensitivity(sens)
            print("\n" + sens_text)
            sens_out = _default_path("screener_sensitivity.md")
            with open(sens_out, "w", encoding="utf-8") as fp:
                fp.write(sens_text)
            print(f"敏感性报告已写出: {sens_out}")
        return 0

    # ---- run ----
    technical = not getattr(args, "no_technical", False)
    top_n = getattr(args, "top", 40)

    if getattr(args, "load_csv", None):
        bundle = datasource.load_snapshot_csv(args.load_csv)
        src = f"CSV回放: {args.load_csv}"
        enrich = False
    else:
        bundle = datasource.fetch_snapshot()
        src = bundle.describe()
        if getattr(args, "save_csv", None):
            datasource.save_snapshot_csv(bundle.df, args.save_csv)
            print(f"行情快照已保存: {args.save_csv}")
        enrich = True

    df = bundle.df
    tech_coverage = 0.0
    if enrich and technical:
        df, tech_coverage = datasource.enrich_technical(df, top_n=getattr(args, "top_tech", 200))

    universe = len(df)
    scores = scoring.score_frame(df, cfg, technical_enabled=technical)
    # score_frame 返回通过硬性过滤并完成评分的全部标的（含 none 评级）
    eligible = len(scores)
    tech_on = technical and enrich

    result = ScreenerResult(
        generated_at=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        data_source=src,
        snapshot_time=bundle.as_of,
        as_of_kind=bundle.as_of_kind,
        fallback_chain=bundle.fallback_chain,
        coverage=round(bundle.coverage * (tech_coverage if tech_on else 1.0), 4),
        universe_size=universe,
        screened_size=eligible,
        scored_size=len(scores),
        technical_enabled=tech_on,
        config_summary={
            "weights": cfg.weights,
            "tiers": cfg.tiers,
            "filters": cfg.filters,
        },
        scores=scores,
    )

    _print_summary(result, top_n)

    # 运行审计（CLI 路径同样记录，与 Web 服务路径口径一致）
    try:
        from .audit import audit
        audit.record({
            "generated_at": result.generated_at,
            "source": result.data_source,
            "fallback_chain": result.fallback_chain,
            "as_of": result.snapshot_time,
            "as_of_kind": result.as_of_kind,
            "coverage": result.coverage,
            "universe_size": result.universe_size,
            "screened_size": result.screened_size,
            "scored_size": result.scored_size,
            "strong_count": sum(1 for s in scores if s.tier == "strong"),
            "technical_enabled": tech_on,
            "duration_ms": 0,
        })
    except Exception:  # noqa: BLE001
        pass

    if not getattr(args, "no_save", False):
        md_path = getattr(args, "report", None) or _default_path("screener_report.md")
        json_path = getattr(args, "json_out", None) or _default_path("screener_result.json")
        written = report_mod.write_report(result, cfg, md_path=md_path, json_path=json_path, top_n=top_n)
        for k, v in written.items():
            print(f"报告已写出({k}): {v}")

    # 实时模式用完关连接
    if bundle.source not in ("csv-replay",):
        try:
            datasource.close()
        except Exception:  # noqa: BLE001
            pass
    return 0


def main() -> None:
    """独立运行入口：python -m finfeed.screener"""
    parser = argparse.ArgumentParser(description="FinFeed 选股评分模块")
    add_arguments(parser)
    # 未指定 --screener 时默认 run（方便独立调试）
    parser.set_defaults(screener="run", load_csv=None, save_csv=None,
                        no_technical=False, no_save=False, config=None,
                        report=None, json_out=None, top=40, top_tech=200)
    args = parser.parse_args()
    raise SystemExit(cmd_screener(args))


if __name__ == "__main__":
    main()
