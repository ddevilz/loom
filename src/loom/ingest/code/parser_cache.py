from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, cast

_PARSER_LOCAL = threading.local()


def get_cached_parser[T](key: str, factory: Callable[[], T]) -> T:
    cache = cast(dict[str, Any] | None, getattr(_PARSER_LOCAL, "cache", None))
    if cache is None:
        cache = {}
        _PARSER_LOCAL.cache = cache
    parser = cache.get(key)
    if parser is None:
        parser = factory()
        cache[key] = parser
    return cast(T, parser)
