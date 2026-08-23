# -*- coding: utf-8 -*-
"""临时冒烟测试：桩化 easy_tdx，验证 anomaly/alerting/ws 逻辑可导入且可运行。"""
import sys, types

# ---- 桩化 easy_tdx ----
easy = types.ModuleType("easy_tdx")
easy.MacClient = object
easy.BoardType = types.SimpleNamespace(HY="HY", GN="GN")
easy.Category = types.SimpleNamespace(A="A", ZS="ZS")
easy.SortOrder = types.SimpleNamespace(ASC="asc", DESC="desc")
easy.SortType = types.SimpleNamespace(CODE="code")
codec = types.ModuleType("easy_tdx.codec")
bitmap = types.ModuleType("easy_tdx.codec.bitmap")
bitmap.FieldBit = types.SimpleNamespace(
    MAIN_NET_AMOUNT="x", MAIN_NET_RATIO="x", MAIN_NET_5M_AMOUNT="x",
    MAIN_NET_3D_AMOUNT="x", MAIN_NET_5D_AMOUNT="x", AMOUNT="x", TURNOVER="x")
bitmap.PresetField = types.SimpleNamespace(BASIC="b", VOLUME="v")
codec.bitmap = bitmap
easy.codec = codec
exc = types.ModuleType("easy_tdx.exceptions")
exc.TdxError = Exception
exc.TdxConnectionError = Exception
easy.exceptions = exc
sys.modules["easy_tdx"] = easy
sys.modules["easy_tdx.codec"] = codec
sys.modules["easy_tdx.codec.bitmap"] = bitmap
sys.modules["easy_tdx.exceptions"] = exc
# ---- 桩化可选依赖（确保惰性导入路径存在） ----
for mod in ("finfeed.market.alerting", "finfeed.market.ws_feed", "finfeed.alerts.subscription"):
    sys.modules.setdefault(mod, types.ModuleType(mod))

sys.path.insert(0, r"E:\VibeCoding\FinFeed")

from finfeed.capital_dashboard.models import (
    MarketSnapshot, BoardFlow, StockFlow, MarketBreadth, MarketStats, IndexQuote, UnusualEvent)
from finfeed.capital_dashboard.anomaly import detector, AnomalyReport
from finfeed.capital_dashboard.alerting import manager

# ---- 构造合成数据 ----
def mk_board(code, name, change, main_net, amount, btype="HY"):
    return BoardFlow(code=code, name=name, board_type=btype, change_pct=change,
                     amount=amount, main_net=main_net, up_count=10, down_count=5, member_count=20)

boards = [
    mk_board("B1", "强势板块", 3.2, 8e8, 5e9),
    mk_board("B2", "弱势板块", -2.5, -6e8, 4e9),
    mk_board("B3", "背离板块", 1.8, -2e8, 3e9),
    mk_board("B4", "微盘噪声", 0.1, 5e5, 1e6),  # 应被流动性门槛过滤
]
stocks = [
    StockFlow(code="600000", name="涨停背离股", price=11.0, change_pct=10.0, amount=2e9,
              main_net=-3e7, main_net_5m=-1e7, main_net_ratio=-1.5),
    StockFlow(code="000001", name="主力异动股", price=9.0, change_pct=1.0, amount=3e9,
              main_net=1e8, main_net_5m=9e7, main_net_ratio=3.0),
]
snap = MarketSnapshot(
    ts="2026-08-24 10:00:00", ts_label="10:00:00",
    indices=[IndexQuote(code="999999", name="上证指数", price=3200.0, change_pct=0.5, amount=3e11)],
    stocks=stocks, boards=boards,
    unusual=[UnusualEvent(code="600000", name="涨停背离股", time="10:00:01", desc="涨停", value="", unusual_type=1)],
    breadth=MarketBreadth(up=2000, down=1500, flat=100, total=3600, limit_up=50, limit_down=10),
    stats=MarketStats(total_amount=4e11, total_main_net=1e9, main_in_stocks=1800, main_out_stocks=1500),
)

# 历史：让 B1 的净占比逐步抬升，制造统计偏离
history = []
for i in range(8):
    hb = [mk_board(b.code, b.name, b.change_pct, b.main_net * (0.3 + 0.05*i), b.amount, b.board_type)
          for b in boards]
    history.append(MarketSnapshot(ts=f"t{i}", ts_label=f"t{i}", boards=hb))

rep = detector.detect(snap, history)
print("=== 异常检测 ===")
print("板块异常:", [(a.board_name, a.kind, a.z_score, a.confidence, a.severity) for a in rep.boards])
print("个股异常:", [(a.name, a.kind, a.confidence) for a in rep.stocks])

# 连续调用以跨越滞回确认阈值（需要 ≥3 轮观测；history 仅含历史轮，不含当轮，贴近生产）
for _ in range(3):
    rep4 = detector.detect(snap, history)
print("多轮后板块异常数:", len(rep4.boards))
print("多轮后个股异常数:", len(rep4.stocks))
print("多轮后板块异常明细:", [(a.board_name, a.kind, a.z_score, a.confidence, a.severity) for a in rep4.boards])
print("多轮后个股异常明细:", [(a.name, a.kind, a.confidence) for a in rep4.stocks])

# 告警评估（基于已确认的异常）
alerts = manager.evaluate(snap, rep4)
print("=== 告警 ===")
print("生成告警:", [(a.source, a.kind, a.severity, a.title) for a in alerts])
print("近期告警数:", len(manager.get_recent()))
print("告警配置:", manager.get_config())

# WS 负载构建（不启动服务，仅验证函数存在）
from finfeed.capital_dashboard import ws
print("WS 模块导入 OK, ws_router 路由数:", len(ws.ws_router.routes))

# ---- 信号可观测性（P2-7）：跟随验证命中率 ----
from finfeed.capital_dashboard.observability import SignalTracker

st = SignalTracker()  # 独立实例，避免污染生产单例
st.record_round(snap, rep4, None)
s1 = st.summary()
print("\n=== 可观测性（第 1 轮） ===")
print("fired=%d open=%d resolved=%d by_kind=%s" % (
    s1["total_fired"], s1["open"], s1["resolved"], sorted(s1["by_kind"].keys())))

# 后续轮：B1 继续走强(命中看多)、B2 继续走弱(命中看空)、B3 反弹回落(背离看多未延续 -> 未命中)
snap2_boards = [
    mk_board("B1", "强势板块", 4.2, 8e8, 5e9),
    mk_board("B2", "弱势板块", -3.1, -6e8, 4e9),
    mk_board("B3", "背离板块", 1.0, -2e8, 3e9),
    mk_board("B4", "微盘噪声", 0.1, 5e5, 1e6),
]
snap2 = MarketSnapshot(ts="2026-08-24 10:00:08", ts_label="10:00:08",
                       boards=snap2_boards, stocks=stocks)
for _ in range(6):
    st.record_round(snap2, AnomalyReport(boards=rep4.boards, stocks=rep4.stocks), None)
s2 = st.summary()
print("\n=== 可观测性（6 轮后） ===")
print("fired=%d open=%d resolved=%d hits=%d misses=%d hit_rate=%s" % (
    s2["total_fired"], s2["open"], s2["resolved"], s2["hits"], s2["misses"], s2["hit_rate"]))
print("by_kind:", s2["by_kind"])
print("recent 样本:", [(p["name"], p["kind"], p["outcome"]) for p in s2["recent"]][-4:])
assert s2["resolved"] > 0 and s2["hits"] > 0 and s2["misses"] > 0, "应同时存在命中与未命中样本"
assert s2["hit_rate"] is not None and 0 < s2["hit_rate"] < 1, "命中率应介于 0~1"
print("可观测性断言通过")

print("\nALL_OK")
