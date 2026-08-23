from finfeed.application.news_service import NewsService


def test_category_query_is_cached_and_uses_category_filter():
    calls = []
    cache = {}
    service = NewsService(
        lambda **filters: (calls.append(filters) or (["item"], 1)),
        lambda items, total, offset, limit, names: {"items": items, "total": total},
        cache.get,
        cache.__setitem__,
        lambda: None,
    )
    params = {"page_size": 20, "offset": 0, "keyword": None, "start_ts": None, "end_ts": None,
              "sentiment": None, "is_favorite": None, "stock": None, "min_importance": None, "source": None}

    first = service.list_category(category="flash", params=params, display_names=[], cache_key="flash:1")
    second = service.list_category(category="flash", params=params, display_names=[], cache_key="flash:1")

    assert first == second == {"items": ["item"], "total": 1}
    assert calls == [{
        "limit": 20, "offset": 0, "keyword": None, "start_ts": None, "end_ts": None,
        "sentiment": None, "is_favorite": None, "stock_name": None,
        "min_importance": None, "category": "flash",
    }]


def test_mutations_invalidate_api_cache():
    invalidations = []
    service = NewsService(lambda **_: ([], 0), lambda *_: {}, lambda _: None, lambda *_: None,
                          lambda: invalidations.append(True))

    assert service.set_favorite(1, lambda _: True) is True
    service.mark_read(1, True, lambda *_: None)
    assert invalidations == [True, True]
