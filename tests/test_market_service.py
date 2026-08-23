from finfeed.application.market_service import MarketService, bounded_int, first_query_value


def test_query_helpers_handle_missing_invalid_and_out_of_range_values():
    query = {"limit": ["999"], "bad": ["abc"], "name": ["market", "ignored"]}

    assert first_query_value(query, "name") == "market"
    assert first_query_value(query, "missing", "fallback") == "fallback"
    assert bounded_int(query, "limit", 40, maximum=80) == 80
    assert bounded_int(query, "bad", 40) == 40
    assert bounded_int({}, "missing", 40) == 40


def test_get_dates_returns_full_structure_without_errors():
    """读本地 SQLite，无数据表/无数据时安全回退，不抛异常。"""
    svc = MarketService()
    result = svc.get_dates("2026-08-24")
    for key in ("billboard", "limit_pool", "sentiment", "forecast", "ipo",
                "money_flow", "margin_detail", "daily_bar"):
        assert key in result
    assert isinstance(result["has_billboard"], bool)
    assert isinstance(result["has_limit_pool"], bool)
    assert isinstance(result["default_date"], str) and result["default_date"]


def test_run_action_status_is_empty_initially():
    svc = MarketService()
    result = svc.run_action({"action": ["status"]})
    assert result["success"] is True
    assert result["data"] == {}


def test_run_action_rejects_unknown_action():
    svc = MarketService()
    result = svc.run_action({"action": ["bogus"]})
    assert result["success"] is False
    assert "未知操作" in result["error"]
