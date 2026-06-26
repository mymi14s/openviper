"""Utility data structures for headers, query params, and multi-dicts.

Hot-path classes (``Headers``, ``QueryParams``, ``ImmutableMultiDict``) are
backed by ``multidict`` C extensions for O(1) lookups and zero-copy iteration.
"""

from __future__ import annotations

import contextlib
import typing as t
import urllib.parse
from collections.abc import Iterator

from multidict import CIMultiDict, MultiDict

if t.TYPE_CHECKING:
    from openviper.http.uploads import UploadFile

__all__ = [
    "Headers",
    "QueryParams",
    "ImmutableMultiDict",
    "check_no_crlf",
    "unique_keys",
    "unique_items",
]


def check_no_crlf(value: str, label: str = "Header value") -> None:
    """Raise ValueError if *value* contains CR or LF (HTTP response splitting guard)."""
    if "\r" in value or "\n" in value:
        raise ValueError(f"{label} must not contain CR or LF characters")


def unique_keys(iterable: t.Iterable[str]) -> Iterator[str]:
    """Yield each key from *iterable* only once, preserving first-occurrence order."""
    seen: set[str] = set()
    for k in iterable:
        if k not in seen:
            seen.add(k)
            yield k


def unique_items(iterable: t.Iterable[tuple[str, str]]) -> Iterator[tuple[str, str]]:
    """Yield each (key, value) pair from *iterable* only once per key,
    preserving first-occurrence order."""
    seen: set[str] = set()
    for k, v in iterable:
        if k not in seen:
            seen.add(k)
            yield k, v


class Headers:
    """Immutable, case-insensitive HTTP headers backed by a raw ASGI list.

    Lookups are O(1) via a ``multidict.CIMultiDict`` C-extension store.
    The original bytes list is preserved as-is for ``raw`` so ASGI callers
    receive the exact format they expect.

    Args:
        raw: List of ``[name_bytes, value_bytes]`` pairs (ASGI format).
    """

    def __init__(self, raw: list[list[bytes]] | list[tuple[bytes, bytes]]) -> None:
        self._list: list[tuple[bytes, bytes]] = [(k.lower(), v) for k, v in raw]
        for k, v in self._list:
            check_no_crlf(k.decode("latin-1"), "Header name")
            check_no_crlf(v.decode("latin-1"), "Header value")
        self._store: CIMultiDict[str] = CIMultiDict(
            (k.decode("latin-1"), v.decode("latin-1")) for k, v in self._list
        )

    def __getitem__(self, key: str) -> str:
        return self._store[key]

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._store.get(key, default)

    def getlist(self, key: str) -> list[str]:
        return self._store.getall(key, [])

    def keys(self) -> list[str]:
        return list(unique_keys(k.decode("latin-1") for k, _ in self._list))

    def values(self) -> list[str]:
        return [v.decode("latin-1") for _, v in self._list]

    def items(self) -> list[tuple[str, str]]:
        return [(k.decode("latin-1"), v.decode("latin-1")) for k, v in self._list]

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        return key in self._store

    def __iter__(self) -> Iterator[str]:
        yield from unique_keys(k.decode("latin-1") for k, _ in self._list)

    def __len__(self) -> int:
        return len(self._list)

    def __repr__(self) -> str:
        return f"Headers({dict(self.items())!r})"

    @property
    def raw(self) -> list[tuple[bytes, bytes]]:
        return self._list


class MutableHeaders(Headers):
    """Mutable version of ``Headers`` for building responses.

    Both the bytes list (``raw``) and the C-backed ``CIMultiDict`` are kept
    in sync so reads stay O(1) even after mutations.
    """

    def __init__(self, raw: list[list[bytes]] | list[tuple[bytes, bytes]] | None = None) -> None:
        super().__init__(raw or [])

    def set(self, key: str, value: str) -> None:
        """Replace all existing values for *key* with *value*."""
        check_no_crlf(key, "Header name")
        check_no_crlf(value, "Header value")
        bkey = key.lower().encode("latin-1")
        bval = value.encode("latin-1")
        # Preserve first-occurrence position in _list for stable iteration order.
        found = False
        new_list: list[tuple[bytes, bytes]] = []
        for k, v in self._list:
            if k == bkey:
                if not found:
                    new_list.append((bkey, bval))
                    found = True
            else:
                new_list.append((k, v))
        if not found:
            new_list.append((bkey, bval))
        self._list = new_list
        # CIMultiDict.__setitem__ replaces ALL occurrences atomically.
        self._store[key] = value

    def append(self, key: str, value: str) -> None:
        """Append a new *key*/*value* pair (allows duplicate header names)."""
        check_no_crlf(key, "Header name")
        check_no_crlf(value, "Header value")
        self._list.append((key.lower().encode("latin-1"), value.encode("latin-1")))
        self._store.add(key, value)

    def delete(self, key: str) -> None:
        """Remove all entries for *key*."""
        bkey = key.lower().encode("latin-1")
        self._list = [(k, v) for k, v in self._list if k != bkey]
        with contextlib.suppress(KeyError):
            del self._store[key]

    def __setitem__(self, key: str, value: str) -> None:
        self.set(key, value)


class QueryParams:
    """Immutable query parameter mapping (supports multi-values).

    Backed by ``multidict.MultiDict`` (C extension) for O(1) key access.

    Args:
        query_string: Raw query string like ``"a=1&b=2&a=3"``.
    """

    def __init__(self, query_string: str) -> None:
        pairs = urllib.parse.parse_qsl(query_string, keep_blank_values=True)
        self._store: MultiDict[str] = MultiDict(pairs)

    def get(self, key: str, default: str | None = None) -> str | None:
        vals = self._store.getall(key, None)
        if vals:
            return vals[0]
        return default

    def getlist(self, key: str) -> list[str]:
        return self._store.getall(key, [])

    def __getitem__(self, key: str) -> str:
        try:
            return self._store[key]
        except KeyError:
            raise KeyError(key) from None

    def __contains__(self, key: object) -> bool:
        return key in self._store

    def __iter__(self) -> Iterator[str]:
        return unique_keys(self._store)

    def __len__(self) -> int:
        return len(set(self._store.keys()))

    def items(self) -> list[tuple[str, str]]:
        return list(unique_items(self._store.items()))

    def multi_items(self) -> list[tuple[str, str]]:
        return list(self._store.items())

    def keys(self) -> list[str]:
        return list(unique_keys(self._store))

    def __repr__(self) -> str:
        return f"QueryParams({self.items()!r})"


class ImmutableMultiDict:
    """Ordered multi-value dict (used for form data).

    Backed by ``multidict.MultiDict`` (C extension).
    """

    def __init__(self, items: list[tuple[str, str | UploadFile]]) -> None:
        self._store: MultiDict[str | UploadFile] = MultiDict(items)

    def get(self, key: str, default: str | UploadFile | None = None) -> str | UploadFile | None:
        return self._store.get(key, default)

    def getlist(self, key: str) -> list[str | UploadFile]:
        return self._store.getall(key, [])

    def __getitem__(self, key: str) -> str | UploadFile:
        return self._store[key]

    def __contains__(self, key: object) -> bool:
        return key in self._store

    def __iter__(self) -> Iterator[str]:
        seen: set[str] = set()
        for k in self._store:
            if k not in seen:
                seen.add(k)
                yield k

    def items(self) -> list[tuple[str, str | UploadFile]]:
        seen: set[str] = set()
        result: list[tuple[str, str | UploadFile]] = []
        for k, v in self._store.items():
            if k not in seen:
                seen.add(k)
                result.append((k, v))
        return result

    def multi_items(self) -> list[tuple[str, str | UploadFile]]:
        return list(self._store.items())

    def __len__(self) -> int:
        return len(set(self._store.keys()))

    def __repr__(self) -> str:
        return f"ImmutableMultiDict({list(self._store.items())!r})"
