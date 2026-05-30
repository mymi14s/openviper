"""Isolated cache utilities for tests."""


class TestCache:
    """Small async in-memory cache for tests."""

    __test__ = False

    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    async def get(self, key: str) -> object:
        return self.values.get(key)

    async def set(self, key: str, value: object) -> None:
        self.values[key] = value

    async def clear(self) -> None:
        self.values.clear()


def assert_cache_key(cache: TestCache, key: str) -> None:
    assert key in cache.values, f"Expected cache key {key!r} to be present."
