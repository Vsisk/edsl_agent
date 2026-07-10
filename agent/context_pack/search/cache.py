from collections import OrderedDict
from collections.abc import Callable, Iterable
from typing import Any


CacheKey = tuple[str, str, str, str]


class IndexCache:
    def __init__(self, max_entries: int = 16) -> None:
        self.max_entries = max_entries
        self._items: OrderedDict[CacheKey, tuple[Any, ...]] = OrderedDict()

    def get(self, key: CacheKey) -> tuple[Any, ...] | None:
        value = self._items.get(key)
        if value is not None:
            self._items.move_to_end(key)
        return value

    def get_or_build(self, key: CacheKey, builder: Callable[[], Iterable[Any]]) -> tuple[Any, ...]:
        existing = self.get(key)
        if existing is not None:
            return existing
        value = tuple(builder())
        self._items[key] = value
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)
        return value
