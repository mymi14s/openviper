"""Integration tests for openviper.utils.datastructures."""

from __future__ import annotations

import pytest

from openviper.utils.datastructures import Headers, ImmutableMultiDict, MutableHeaders, QueryParams

# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------


class TestHeaders:
    def test_getitem_existing(self):
        h = Headers([(b"content-type", b"application/json")])
        assert h["content-type"] == "application/json"

    def test_getitem_case_insensitive(self):
        h = Headers([(b"Content-Type", b"text/html")])
        assert h["content-type"] == "text/html"
        assert h["Content-Type"] == "text/html"

    def test_getitem_missing_raises_keyerror(self):
        h = Headers([])
        with pytest.raises(KeyError):
            _ = h["missing"]

    def test_get_existing(self):
        h = Headers([(b"x-custom", b"value")])
        assert h.get("x-custom") == "value"

    def test_get_missing_returns_default(self):
        h = Headers([])
        assert h.get("missing") is None
        assert h.get("missing", "fallback") == "fallback"

    def test_getlist_single_value(self):
        h = Headers([(b"x-foo", b"bar")])
        assert h.getlist("x-foo") == ["bar"]

    def test_getlist_multiple_values(self):
        h = Headers([(b"accept", b"text/html"), (b"accept", b"application/json")])
        result = h.getlist("accept")
        assert result == ["text/html", "application/json"]

    def test_getlist_missing_returns_empty(self):
        h = Headers([])
        assert h.getlist("nope") == []

    def test_keys(self):
        h = Headers([(b"a", b"1"), (b"b", b"2")])
        assert set(h.keys()) == {"a", "b"}

    def test_values(self):
        h = Headers([(b"a", b"1"), (b"b", b"2")])
        assert set(h.values()) == {"1", "2"}

    def test_items(self):
        h = Headers([(b"a", b"1")])
        assert h.items() == [("a", "1")]

    def test_contains_true(self):
        h = Headers([(b"x-foo", b"bar")])
        assert "x-foo" in h

    def test_contains_false(self):
        h = Headers([])
        assert "nope" not in h

    def test_contains_non_string(self):
        h = Headers([(b"x", b"y")])
        assert 123 not in h

    def test_iter(self):
        h = Headers([(b"a", b"1"), (b"b", b"2")])
        assert list(h) == ["a", "b"]

    def test_len(self):
        h = Headers([(b"a", b"1"), (b"b", b"2"), (b"c", b"3")])
        assert len(h) == 3

    def test_repr(self):
        h = Headers([(b"x", b"y")])
        r = repr(h)
        assert "Headers" in r

    def test_raw_property(self):
        raw = [(b"a", b"1")]
        h = Headers(raw)
        assert h.raw == [(b"a", b"1")]

    def test_empty_headers(self):
        h = Headers([])
        assert len(h) == 0
        assert list(h) == []

    def test_list_pairs_accepted(self):
        h = Headers([[b"x", b"y"]])
        assert h["x"] == "y"


# ---------------------------------------------------------------------------
# MutableHeaders
# ---------------------------------------------------------------------------


class TestMutableHeaders:
    def test_init_empty(self):
        h = MutableHeaders()
        assert len(h) == 0

    def test_init_none(self):
        h = MutableHeaders(None)
        assert len(h) == 0

    def test_set_new_key(self):
        h = MutableHeaders()
        h.set("x-custom", "hello")
        assert h["x-custom"] == "hello"

    def test_set_existing_key_replaces(self):
        h = MutableHeaders([(b"x", b"old")])
        h.set("x", "new")
        assert h["x"] == "new"
        # Only one entry
        assert h.getlist("x") == ["new"]

    def test_setitem_alias(self):
        h = MutableHeaders()
        h["content-type"] = "text/plain"
        assert h["content-type"] == "text/plain"

    def test_append_adds_duplicate(self):
        h = MutableHeaders()
        h.append("accept", "text/html")
        h.append("accept", "application/json")
        assert h.getlist("accept") == ["text/html", "application/json"]

    def test_delete_removes_entries(self):
        h = MutableHeaders([(b"x", b"1"), (b"x", b"2"), (b"y", b"3")])
        h.delete("x")
        assert "x" not in h
        assert "y" in h

    def test_delete_missing_key_no_error(self):
        h = MutableHeaders()
        h.delete("nonexistent")  # Should not raise


# ---------------------------------------------------------------------------
# QueryParams
# ---------------------------------------------------------------------------


class TestQueryParams:
    def test_single_param(self):
        qp = QueryParams("a=1")
        assert qp["a"] == "1"
        assert qp.get("a") == "1"

    def test_multiple_params(self):
        qp = QueryParams("a=1&b=2")
        assert qp["a"] == "1"
        assert qp["b"] == "2"

    def test_multi_value_get_returns_first(self):
        qp = QueryParams("a=1&a=2")
        assert qp.get("a") == "1"

    def test_getlist_multi_value(self):
        qp = QueryParams("a=1&a=2&a=3")
        assert qp.getlist("a") == ["1", "2", "3"]

    def test_getlist_missing_returns_empty(self):
        qp = QueryParams("")
        assert qp.getlist("nope") == []

    def test_get_missing_returns_default(self):
        qp = QueryParams("a=1")
        assert qp.get("b") is None
        assert qp.get("b", "default") == "default"

    def test_getitem_missing_raises_keyerror(self):
        qp = QueryParams("")
        with pytest.raises(KeyError):
            _ = qp["missing"]

    def test_contains_true(self):
        qp = QueryParams("a=1")
        assert "a" in qp

    def test_contains_false(self):
        qp = QueryParams("")
        assert "nope" not in qp

    def test_iter(self):
        qp = QueryParams("a=1&b=2")
        keys = list(qp)
        assert "a" in keys
        assert "b" in keys

    def test_len(self):
        qp = QueryParams("a=1&b=2")
        assert len(qp) == 2

    def test_len_multi_value_counts_as_one(self):
        qp = QueryParams("a=1&a=2")
        assert len(qp) == 1

    def test_items(self):
        qp = QueryParams("a=1&b=2")
        items = qp.items()
        assert ("a", "1") in items

    def test_multi_items(self):
        qp = QueryParams("a=1&a=2")
        items = qp.multi_items()
        assert ("a", "1") in items
        assert ("a", "2") in items

    def test_keys(self):
        qp = QueryParams("a=1&b=2")
        assert set(qp.keys()) == {"a", "b"}

    def test_empty_string(self):
        qp = QueryParams("")
        assert len(qp) == 0

    def test_blank_values_kept(self):
        qp = QueryParams("a=&b=")
        assert qp.get("a") == ""
        assert qp.get("b") == ""

    def test_repr(self):
        qp = QueryParams("a=1")
        r = repr(qp)
        assert "QueryParams" in r

    def test_url_encoded_values(self):
        qp = QueryParams("q=hello+world")
        assert qp.get("q") is not None


# ---------------------------------------------------------------------------
# ImmutableMultiDict
# ---------------------------------------------------------------------------


class TestImmutableMultiDict:
    def test_get_existing(self):
        d = ImmutableMultiDict([("a", "1"), ("b", "2")])
        assert d.get("a") == "1"

    def test_get_missing_returns_default(self):
        d = ImmutableMultiDict([])
        assert d.get("missing") is None
        assert d.get("missing", "fallback") == "fallback"

    def test_getlist_single(self):
        d = ImmutableMultiDict([("a", "1")])
        assert d.getlist("a") == ["1"]

    def test_getlist_multiple(self):
        d = ImmutableMultiDict([("a", "1"), ("a", "2"), ("a", "3")])
        assert d.getlist("a") == ["1", "2", "3"]

    def test_getlist_missing_returns_empty(self):
        d = ImmutableMultiDict([])
        assert d.getlist("nope") == []

    def test_getitem_returns_first(self):
        d = ImmutableMultiDict([("a", "first"), ("a", "second")])
        assert d["a"] == "first"

    def test_getitem_missing_raises_keyerror(self):
        d = ImmutableMultiDict([])
        with pytest.raises(KeyError):
            _ = d["nope"]

    def test_contains_true(self):
        d = ImmutableMultiDict([("a", "1")])
        assert "a" in d

    def test_contains_false(self):
        d = ImmutableMultiDict([])
        assert "nope" not in d

    def test_iter_unique_keys(self):
        d = ImmutableMultiDict([("a", "1"), ("a", "2"), ("b", "3")])
        keys = list(d)
        assert keys.count("a") == 1
        assert "b" in keys

    def test_items_unique_keys(self):
        d = ImmutableMultiDict([("a", "1"), ("a", "2")])
        items = d.items()
        # Only first for "a"
        assert ("a", "1") in items
        assert ("a", "2") not in items

    def test_multi_items_all_values(self):
        d = ImmutableMultiDict([("a", "1"), ("a", "2")])
        items = d.multi_items()
        assert ("a", "1") in items
        assert ("a", "2") in items

    def test_len_counts_unique_keys(self):
        d = ImmutableMultiDict([("a", "1"), ("a", "2"), ("b", "3")])
        assert len(d) == 2

    def test_repr(self):
        d = ImmutableMultiDict([("a", "1")])
        r = repr(d)
        assert "ImmutableMultiDict" in r

    def test_empty(self):
        d = ImmutableMultiDict([])
        assert len(d) == 0
