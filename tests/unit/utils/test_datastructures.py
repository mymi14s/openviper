"""Unit tests for openviper.utils.datastructures — Headers, MutableHeaders, QueryParams, ImmutableMultiDict."""  # noqa: E501

import pytest

from openviper.utils.datastructures import (
    Headers,
    ImmutableMultiDict,
    MutableHeaders,
    QueryParams,
    _check_no_crlf,
)


class TestHeaders:
    def _make(self, pairs):
        return Headers([(k.encode(), v.encode()) for k, v in pairs])

    def test_getitem(self):
        h = self._make([("Content-Type", "application/json")])
        assert h["content-type"] == "application/json"

    def test_get_default(self):
        h = self._make([])
        assert h.get("missing", "default") == "default"

    def test_getlist(self):
        h = self._make([("Set-Cookie", "a=1"), ("Set-Cookie", "b=2")])
        assert h.getlist("set-cookie") == ["a=1", "b=2"]

    def test_keys_values_items(self):
        h = self._make([("X-A", "1"), ("X-B", "2")])
        assert len(h.keys()) == 2
        assert len(h.values()) == 2
        assert len(h.items()) == 2

    def test_contains(self):
        h = self._make([("X-Test", "yes")])
        assert "X-Test" in h
        assert "Missing" not in h
        assert 42 not in h

    def test_iter(self):
        h = self._make([("A", "1"), ("B", "2")])
        assert list(h) == ["a", "b"]

    def test_len(self):
        h = self._make([("A", "1"), ("B", "2")])
        assert len(h) == 2

    def test_repr(self):
        h = self._make([("X-Test", "val")])
        assert "Headers" in repr(h)

    def test_raw(self):
        h = self._make([("X-Test", "val")])
        assert isinstance(h.raw, list)
        assert h.raw[0] == (b"x-test", b"val")


class TestMutableHeaders:
    def test_set_replaces(self):
        h = MutableHeaders([(b"x-test", b"old")])
        h.set("x-test", "new")
        assert h["x-test"] == "new"

    def test_set_adds_new(self):
        h = MutableHeaders([])
        h.set("x-new", "val")
        assert h["x-new"] == "val"

    def test_append(self):
        h = MutableHeaders([])
        h.append("set-cookie", "a=1")
        h.append("set-cookie", "b=2")
        assert h.getlist("set-cookie") == ["a=1", "b=2"]

    def test_delete(self):
        h = MutableHeaders([(b"x-test", b"val")])
        h.delete("x-test")
        assert "x-test" not in h

    def test_delete_missing_no_error(self):
        h = MutableHeaders([])
        h.delete("missing")  # Should not raise

    def test_setitem(self):
        h = MutableHeaders([])
        h["x-test"] = "val"
        assert h["x-test"] == "val"

    def test_set_deduplicates(self):
        h = MutableHeaders([(b"x-test", b"a"), (b"x-test", b"b")])
        h.set("x-test", "c")
        assert h.getlist("x-test") == ["c"]


class TestQueryParams:
    def test_basic_parsing(self):
        q = QueryParams("a=1&b=2")
        assert q["a"] == "1"
        assert q["b"] == "2"

    def test_multi_values(self):
        q = QueryParams("a=1&a=2&a=3")
        assert q.getlist("a") == ["1", "2", "3"]
        assert q.get("a") == "1"

    def test_get_default(self):
        q = QueryParams("")
        assert q.get("missing", "default") == "default"

    def test_getitem_missing_raises(self):
        q = QueryParams("")
        with pytest.raises(KeyError):
            q["missing"]

    def test_contains(self):
        q = QueryParams("a=1")
        assert "a" in q
        assert "b" not in q

    def test_iter_unique_keys(self):
        q = QueryParams("a=1&a=2&b=3")
        keys = list(q)
        assert keys == ["a", "b"]

    def test_len_unique_keys(self):
        q = QueryParams("a=1&a=2&b=3")
        assert len(q) == 2

    def test_items_deduped(self):
        q = QueryParams("a=1&a=2")
        assert len(q.items()) == 1

    def test_multi_items(self):
        q = QueryParams("a=1&a=2")
        assert len(q.multi_items()) == 2

    def test_keys_deduped(self):
        q = QueryParams("a=1&a=2&b=3")
        assert q.keys() == ["a", "b"]

    def test_repr(self):
        q = QueryParams("a=1")
        assert "QueryParams" in repr(q)

    def test_blank_values(self):
        q = QueryParams("a=&b=")
        assert q["a"] == ""
        assert q["b"] == ""


class TestImmutableMultiDict:
    def test_basic(self):
        d = ImmutableMultiDict([("a", 1), ("b", 2)])
        assert d["a"] == 1
        assert d.get("c") is None

    def test_getlist(self):
        d = ImmutableMultiDict([("a", 1), ("a", 2)])
        assert d.getlist("a") == [1, 2]

    def test_contains(self):
        d = ImmutableMultiDict([("a", 1)])
        assert "a" in d
        assert "b" not in d

    def test_iter_unique(self):
        d = ImmutableMultiDict([("a", 1), ("a", 2), ("b", 3)])
        assert list(d) == ["a", "b"]

    def test_items_deduped(self):
        d = ImmutableMultiDict([("a", 1), ("a", 2)])
        assert len(d.items()) == 1

    def test_multi_items(self):
        d = ImmutableMultiDict([("a", 1), ("a", 2)])
        assert len(d.multi_items()) == 2

    def test_len(self):
        d = ImmutableMultiDict([("a", 1), ("a", 2), ("b", 3)])
        assert len(d) == 2

    def test_repr(self):
        d = ImmutableMultiDict([("a", 1)])
        assert "ImmutableMultiDict" in repr(d)


class TestCheckNoCRLF:
    def test_raises_on_cr(self):
        """_check_no_crlf raises ValueError on carriage-return."""

        with pytest.raises(ValueError, match="CR or LF"):
            _check_no_crlf("bad\rvalue")

    def test_raises_on_lf(self):
        """_check_no_crlf raises ValueError on line-feed."""

        with pytest.raises(ValueError, match="CR or LF"):
            _check_no_crlf("bad\nvalue")

    def test_passes_clean_value(self):
        """_check_no_crlf does not raise for a clean string."""

        _check_no_crlf("safe-value")  # should not raise
