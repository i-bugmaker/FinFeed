"""Small, framework-independent helpers for market query use cases."""

from __future__ import annotations

from collections.abc import Mapping


def first_query_value(query: Mapping[str, list[str]], key: str, default: str = "") -> str:
    """Read a normalized multi-value query map without index errors."""
    values = query.get(key)
    return values[0] if values else default


def bounded_int(
    query: Mapping[str, list[str]], key: str, default: int, maximum: int = 500, minimum: int = 1
) -> int:
    """Parse and clamp a positive numeric market parameter."""
    try:
        return max(minimum, min(int(first_query_value(query, key, str(default))), maximum))
    except (TypeError, ValueError):
        return default
