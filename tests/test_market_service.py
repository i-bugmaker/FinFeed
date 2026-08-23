from finfeed.application.market_service import bounded_int, first_query_value


def test_query_helpers_handle_missing_invalid_and_out_of_range_values():
    query = {"limit": ["999"], "bad": ["abc"], "name": ["market", "ignored"]}

    assert first_query_value(query, "name") == "market"
    assert first_query_value(query, "missing", "fallback") == "fallback"
    assert bounded_int(query, "limit", 40, maximum=80) == 80
    assert bounded_int(query, "bad", 40) == 40
    assert bounded_int({}, "missing", 40) == 40
