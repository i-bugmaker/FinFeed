#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股模块命令行入口。

用法（通过主程序 main.py 转发）：
    python main.py --screener run                       # 实时拉取 easy-tdx 并评分
    python main.py --screener run --demo                # 离线样例演示
    python main.py --screener run --load-csv snap.csv   # 离线回放已存快照
    python main.py --screener run --no-technical        # 关闭 K 线富化
    python main.py --screener run -o report.md --json-out res.json
    python main.py --screener explain                   # 仅打印方法论

也可独立运行：python -m finfeed.screener run --demo
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
from typing import Any

from . import datasource, report as report_mod, sample_data, scoring
from .config import load_config
from .models import ScreenerResult

logger = logging.getLogger("finfeed.screener.cli")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    """把选股相关参数挂到主 parser（与现有 --market 等同级）。"""
    parser.add_argument(
        "--screener", metavar="ACTION",
        choices=["run", "explain"],
        help="选股模块: run(实时/离线评分) / explain(仅输出方法论)",
    )
    parser.add_argument("--demo", action="store_true", help="使用内置离线样例（无需联网）")
    parser.add_argument("--load-csv", help="从 CSV 快照离线回放（由 --save-csv 生成）")
    parser.add_argument("--save-csv", help="将实时行情快照保存为 CSV（便于离线回放）")
    parser.add_argument("--no-technical", action="store_true", help="关闭 K 线技术面富化")
    parser.add_argument("--top", type=int, default=40, help="报告展示 Top N（默认 40）")
    parser.add_argument("--top-tech", type=int, default=200, help="技术面富化前 N 只候选（默认 200）")
    parser.add_argument("--report", help="Markdown 报告输出路径（默认 ./screener_report.md）")
    parser.add_argument("--json-out", help="JSON 结果输出路径（默认 ./screener_result.json）")
    parser.add_argument("--config", help="自定义评分配置 JSON 路径（覆盖默认权重/阈值）")
    parser.add_argument("--no-save", action="store_true", help="不写文件，仅控制台打印摘要")


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
          f"{'PE':>7} {'综合':>6} {'资金':>5} {'动量':>5} {'估值':>5} {'量价':>5} {'质量':>5} {'评级':<8}")
    for i, s in enumerate(result.scores[:top_n], 1):
        tier = {"strong": "入选", "watch": "关注", "observe": "观察", "none": "—"}.get(s.tier, s.tier)
        print(f"{i:>4} {s.code:<8} {s.name:<10} {s.price:>8.2f} {s.change_pct:>+7.2f} "
              f"{s.pe_ttm:>7.1f} {s.total_score:>6.1f} {s.capital_score:>5.0f} "
              f"{s.momentum_score:>5.0f} {s.valuation_score:>5.0f} {s.liquidity_score:>5.0f} "
              f"{s.quality_score:>5.0f} {tier:<8}")
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

    # ---- run ----
    technical = not getattr(args, "no_technical", False)
    top_n = getattr(args, "top", 40)

    if getattr(args, "demo", False):
        df = sample_data.load_sample_dataframe()
        src = "内置离线样例(demo)"
        enrich = False
    elif getattr(args, "load_csv", None):
        df = datasource.load_snapshot_csv(args.load_csv)
        src = f"CSV回放: {args.load_csv}"
        enrich = False
    else:
        df = datasource.fetch_universe()
        src = "easy-tdx 实时行情"
        if getattr(args, "save_csv", None):
            datasource.save_snapshot_csv(df, args.save_csv)
            print(f"行情快照已保存: {args.save_csv}")
        enrich = True

    if enrich and technical:
        df = datasource.enrich_technical(df, top_n=getattr(args, "top_tech", 200))

    universe = len(df)
    eligible = 0
    for rec in df.to_dict("records"):
        row = scoring.build_factor_row(rec)
        ok, _ = scoring.is_eligible(row, cfg)
        if ok:
            eligible += 1

    scores = scoring.score_frame(df, cfg, technical_enabled=technical)
    tech_on = technical and (enrich or getattr(args, "demo", False)
                             or getattr(args, "load_csv", None) is not None)

    result = ScreenerResult(
        generated_at=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        data_source=src,
        snapshot_time="",
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

    if not getattr(args, "no_save", False):
        md_path = getattr(args, "report", None) or _default_path("screener_report.md")
        json_path = getattr(args, "json_out", None) or _default_path("screener_result.json")
        written = report_mod.write_report(result, cfg, md_path=md_path, json_path=json_path, top_n=top_n)
        for k, v in written.items():
            print(f"报告已写出({k}): {v}")

    # 实时模式用完关连接
    if src == "easy-tdx 实时行情":
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
    parser.set_defaults(screener="run", demo=False, load_csv=None, save_csv=None,
                        no_technical=False, no_save=False, config=None,
                        report=None, json_out=None, top=40, top_tech=200)
    args = parser.parse_args()
    raise SystemExit(cmd_screener(args))


if __name__ == "__main__":
    main()
