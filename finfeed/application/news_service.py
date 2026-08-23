"""Framework-independent use cases for the news feed."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class NewsService:
    """Coordinates repository access, response assembly and cache invalidation.

    Dependencies are injected so the service stays independent of FastAPI and
    can be tested with in-memory fakes.
    """

    def __init__(
        self,
        query_news: Callable[..., tuple[list[Any], int]],
        build_response: Callable[[list[Any], int, int, int, list[str]], dict[str, Any]],
        cache_get: Callable[[str], Any],
        cache_set: Callable[[str, Any], None],
        invalidate_cache: Callable[[], None],
    ) -> None:
        self._query_news = query_news
        self._build_response = build_response
        self._cache_get = cache_get
        self._cache_set = cache_set
        self._invalidate_cache = invalidate_cache

    def list_category(
        self, *, category: str, params: dict[str, Any], display_names: list[str], cache_key: str
    ) -> dict[str, Any]:
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        filters = {
            "limit": params["page_size"], "offset": params["offset"],
            "keyword": params["keyword"], "start_ts": params["start_ts"],
            "end_ts": params["end_ts"], "sentiment": params["sentiment"],
            "is_favorite": params["is_favorite"], "stock_name": params["stock"],
            "min_importance": params["min_importance"], "category": category,
        }
        if params.get("source"):
            filters["source"] = params["source"]
        items, total = self._query_news(**filters)
        result = self._build_response(items, total, params["offset"], params["page_size"], display_names)
        self._cache_set(cache_key, result)
        return result

    def set_favorite(self, news_id: int, toggle: Callable[[int], bool]) -> bool:
        state = toggle(news_id)
        self._invalidate_cache()
        return state

    def mark_read(self, news_id: int, is_read: bool, mark: Callable[[int, bool], None]) -> None:
        mark(news_id, is_read)
        self._invalidate_cache()
