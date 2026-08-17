#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kline_cache 存储层测试

用独立临时库隔离测试，绝不触碰生产 finfeed.db。
通过 monkeypatch database.DB_PATH + 重置单例，使每个用例使用全新临时库。
"""

import time

import finfeed.storage.database as db_mod
import pytest
from finfeed.market import store


@pytest.fixture(autouse=True)
def _temp_db(tmp_path):
    """每个用例独立临时库（含 WAL，由 pytest 自动清理）。"""
    db_mod.DB_PATH = str(tmp_path / "test_kline_cache.db")
    db_mod._global_db = None
    yield
    db_mod._global_db = None


@pytest.fixture()
def kdb(_temp_db):
    store.ensure_market_tables()
    return store


def _row(code="000001", d="2026-08-14", open_=1.0, close=1.5, high=2.0, low=0.5, **kw):
    base = {
        "code": code, "trade_date": d,
        "open": open_, "close": close, "high": high, "low": low,
        "volume": 1000, "amount": 1500.0,
        "pct_chg": 1.0, "amplitude": 2.0, "turnover": 0.5,
    }
    base.update(kw)
    return base


def test_upsert_and_get_ascending(kdb):
    rows = [
        _row(d="2026-08-15"),
        _row(d="2026-08-13"),  # 乱序写入，读回应升序
        _row(d="2026-08-14"),
    ]
    n = kdb.upsert_kline_cache(rows, 101)
    assert n == 3

    got = kdb.get_cached_kline("000001", 101)
    assert [r["trade_date"] for r in got] == ["2026-08-13", "2026-08-14", "2026-08-15"]
    assert got[0]["fetched_at"]  # 内部字段随行返回
    assert got[0]["close"] == 1.5


def test_upsert_idempotent_updates_fetched_at(kdb):
    kdb.upsert_kline_cache([_row()], 101)
    got1 = kdb.get_cached_kline("000001", 101)
    assert len(got1) == 1

    time.sleep(1.1)  # 保证 fetched_at 秒级可区分
    kdb.upsert_kline_cache([_row(open_=9.9)], 101)
    got2 = kdb.get_cached_kline("000001", 101)
    assert len(got2) == 1  # 幂等，不产生重复行
    assert got2[0]["open"] == 9.9  # 值已更新
    assert got2[0]["fetched_at"] > got1[0]["fetched_at"]


def test_get_cached_kline_start_end_filter(kdb):
    kdb.upsert_kline_cache([_row(d="2026-08-13"), _row(d="2026-08-14"), _row(d="2026-08-15")], 101)

    got = kdb.get_cached_kline("000001", 101, start="2026-08-14", end="2026-08-14")
    assert len(got) == 1 and got[0]["trade_date"] == "2026-08-14"

    got2 = kdb.get_cached_kline("000001", 101, start="2026-08-14")
    assert [r["trade_date"] for r in got2] == ["2026-08-14", "2026-08-15"]


def test_get_cached_kline_limit_last_n_ascending(kdb):
    kdb.upsert_kline_cache(
        [_row(d=f"2026-08-{d:02d}") for d in range(11, 16)], 101
    )
    got = kdb.get_cached_kline("000001", 101, limit=3)
    assert [r["trade_date"] for r in got] == ["2026-08-13", "2026-08-14", "2026-08-15"]


def test_get_kline_cache_state(kdb):
    assert kdb.get_kline_cache_state("000001", 101) is None
    kdb.upsert_kline_cache([_row(d="2026-08-13"), _row(d="2026-08-15")], 101)
    st = kdb.get_kline_cache_state("000001", 101)
    assert st["count"] == 2
    assert st["first_date"] == "2026-08-13"
    assert st["last_date"] == "2026-08-15"
    assert st["fetched_at"]


def test_klt_isolation(kdb):
    kdb.upsert_kline_cache([_row()], 101)
    kdb.upsert_kline_cache([_row(d="2026-08-10")], 102)
    assert len(kdb.get_cached_kline("000001", 101)) == 1
    assert len(kdb.get_cached_kline("000001", 102)) == 1
    assert len(kdb.get_cached_kline("000001", 103)) == 0


def test_upsert_missing_fields_defaults(kdb):
    kdb.upsert_kline_cache([{"code": "000001", "trade_date": "2026-08-14"}], 101)
    got = kdb.get_cached_kline("000001", 101)
    assert got[0]["open"] == 0.0
    assert got[0]["volume"] == 0
    assert got[0]["close"] == 0.0
