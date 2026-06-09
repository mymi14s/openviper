"""Unit tests for openviper.utils.datastructures."""

import io

import pytest

from openviper.http.uploads import UploadFile
from openviper.utils.datastructures import (
    Headers,
    ImmutableMultiDict,
    MutableHeaders,
    QueryParams,
    check_no_crlf,
    unique_items,
    unique_keys,
)


class TestCheckNoCRLF:
    def test_raises_on_cr(self):
        with pytest.raises(ValueError, match="CR or LF"):
            check_no_crlf("bad\rvalue")

    def test_raises_on_lf(self):
        with pytest.raises(ValueError, match="CR or LF"):
            check_no_crlf("bad\nvalue")

    def test_raises_on_crlf_combo(self):
        with pytest.raises(ValueError, match="CR or LF"):
            check_no_crlf("bad\r\nvalue")

    def test_raises_on_cr_at_start(self):
        with pytest.raises(ValueError, match="CR or LF"):
            check_no_crlf("\rvalue")

    def test_raises_on_lf_at_end(self):
        with pytest.raises(ValueError, match="CR or LF"):
            check_no_crlf("value\n")

    def test_passes_clean_value(self):
        check_no_crlf("safe-value")

    def test_passes_empty_string(self):
        check_no_crlf("")

    def test_custom_label_in_error(self):
        with pytest.raises(ValueError, match="X-Header"):
            check_no_crlf("bad\rvalue", label="X-Header")

    def test_default_label_in_error(self):
        with pytest.raises(ValueError, match="Header value"):
            check_no_crlf("bad\rvalue")


class TestUniqueKeys:
    def test_deduplicates_consecutive(self):
        assert list(unique_keys(["a", "a", "b"])) == ["a", "b"]

    def test_deduplicates_non_consecutive(self):
        assert list(unique_keys(["a", "b", "a", "c"])) == ["a", "b", "c"]

    def test_preserves_first_occurrence_order(self):
        assert list(unique_keys(["c", "b", "a"])) == ["c", "b", "a"]

    def test_empty_iterable(self):
        assert list(unique_keys([])) == []

    def test_single_element(self):
        assert list(unique_keys(["x"])) == ["x"]

    def test_all_unique(self):
        assert list(unique_keys(["a", "b", "c"])) == ["a", "b", "c"]

    def test_all_same(self):
        assert list(unique_keys(["z", "z", "z"])) == ["z"]


class TestUniqueItems:
    def test_deduplicates_by_key(self):
        result = list(unique_items([("a", 1), ("a", 2), ("b", 3)]))
        assert result == [("a", 1), ("b", 3)]

    def test_preserves_first_value(self):
        result = list(unique_items([("x", "first"), ("x", "second")]))
        assert result == [("x", "first")]

    def test_empty_iterable(self):
        assert list(unique_items([])) == []

    def test_all_unique_keys(self):
        result = list(unique_items([("a", 1), ("b", 2)]))
        assert result == [("a", 1), ("b", 2)]

    def test_preserves_order(self):
        result = list(unique_items([("c", 3), ("a", 1), ("b", 2), ("a", 99)]))
        assert result == [("c", 3), ("a", 1), ("b", 2)]


class TestHeaders:
    def _make(self, pairs):
        return Headers([(k.encode(), v.encode()) for k, v in pairs])

    def _make_list(self, pairs):
        return Headers([[k.encode(), v.encode()] for k, v in pairs])

    # -- construction --

    def test_construct_from_list_of_lists(self):
        h = self._make_list([("Content-Type", "text/html")])
        assert h["content-type"] == "text/html"

    def test_construct_from_list_of_tuples(self):
        h = self._make([("Content-Type", "text/html")])
        assert h["content-type"] == "text/html"

    def test_construct_empty(self):
        h = self._make([])
        assert len(h) == 0
        assert list(h) == []

    def test_construct_rejects_cr_in_name(self):
        with pytest.raises(ValueError, match="Header name"):
            Headers([(b"bad\r-name", b"val")])

    def test_construct_rejects_lf_in_value(self):
        with pytest.raises(ValueError, match="Header value"):
            Headers([(b"x-test", b"bad\nvalue")])

    def test_construct_rejects_crlf_in_value(self):
        with pytest.raises(ValueError, match="Header value"):
            Headers([(b"x-test", b"bad\r\nvalue")])

    # -- __getitem__ --

    def test_getitem_case_insensitive(self):
        h = self._make([("Content-Type", "application/json")])
        assert h["content-type"] == "application/json"
        assert h["Content-Type"] == "application/json"
        assert h["CONTENT-TYPE"] == "application/json"

    def test_getitem_missing_raises_keyerror(self):
        h = self._make([])
        with pytest.raises(KeyError):
            h["missing"]

    # -- get --

    def test_get_existing(self):
        h = self._make([("X-Test", "yes")])
        assert h.get("x-test") == "yes"

    def test_get_missing_returns_none(self):
        h = self._make([])
        assert h.get("missing") is None

    def test_get_missing_custom_default(self):
        h = self._make([])
        assert h.get("missing", "fallback") == "fallback"

    # -- getlist --

    def test_getlist_single_value(self):
        h = self._make([("X-A", "1")])
        assert h.getlist("x-a") == ["1"]

    def test_getlist_multiple_values(self):
        h = self._make([("Set-Cookie", "a=1"), ("Set-Cookie", "b=2")])
        assert h.getlist("set-cookie") == ["a=1", "b=2"]

    def test_getlist_missing_returns_empty(self):
        h = self._make([])
        assert h.getlist("missing") == []

    # -- keys / values / items --

    def test_keys_returns_unique(self):
        h = self._make([("X-A", "1"), ("X-A", "2"), ("X-B", "3")])
        assert h.keys() == ["x-a", "x-b"]

    def test_values_returns_all_including_duplicates(self):
        h = self._make([("X-A", "1"), ("X-A", "2")])
        assert h.values() == ["1", "2"]

    def test_items_returns_all_pairs(self):
        h = self._make([("X-A", "1"), ("X-B", "2")])
        assert h.items() == [("x-a", "1"), ("x-b", "2")]

    def test_items_preserves_duplicate_keys(self):
        h = self._make([("X-A", "1"), ("X-A", "2")])
        assert h.items() == [("x-a", "1"), ("x-a", "2")]

    # -- __contains__ --

    def test_contains_case_insensitive(self):
        h = self._make([("X-Test", "yes")])
        assert "X-Test" in h
        assert "x-test" in h
        assert "X-TEST" in h

    def test_contains_missing(self):
        h = self._make([])
        assert "Missing" not in h

    def test_contains_non_string_returns_false(self):
        h = self._make([("X-Test", "yes")])
        assert 42 not in h
        assert None not in h
        assert b"x-test" not in h

    # -- __iter__ --

    def test_iter_yields_unique_keys(self):
        h = self._make([("A", "1"), ("A", "2"), ("B", "3")])
        assert list(h) == ["a", "b"]

    def test_iter_empty(self):
        h = self._make([])
        assert list(h) == []

    # -- __len__ --

    def test_len_counts_all_entries(self):
        h = self._make([("A", "1"), ("B", "2")])
        assert len(h) == 2

    def test_len_includes_duplicate_keys(self):
        h = self._make([("A", "1"), ("A", "2")])
        assert len(h) == 2

    # -- repr --

    def test_repr(self):
        h = self._make([("X-Test", "val")])
        r = repr(h)
        assert "Headers" in r
        assert "x-test" in r

    # -- raw --

    def test_raw_returns_tuples(self):
        h = self._make([("X-Test", "val")])
        assert isinstance(h.raw, list)
        assert h.raw[0] == (b"x-test", b"val")

    def test_raw_lowercases_keys(self):
        h = self._make([("Content-Type", "text/html")])
        assert h.raw[0][0] == b"content-type"


class TestMutableHeaders:
    # -- construction --

    def test_construct_empty(self):
        h = MutableHeaders()
        assert len(h) == 0

    def test_construct_none_raw(self):
        h = MutableHeaders(None)
        assert len(h) == 0

    def test_construct_with_initial(self):
        h = MutableHeaders([(b"x-test", b"val")])
        assert h["x-test"] == "val"

    # -- set --

    def test_set_replaces_existing(self):
        h = MutableHeaders([(b"x-test", b"old")])
        h.set("x-test", "new")
        assert h["x-test"] == "new"

    def test_set_adds_new_key(self):
        h = MutableHeaders([])
        h.set("x-new", "val")
        assert h["x-new"] == "val"

    def test_set_deduplicates_multiple_entries(self):
        h = MutableHeaders([(b"x-test", b"a"), (b"x-test", b"b")])
        h.set("x-test", "c")
        assert h.getlist("x-test") == ["c"]

    def test_set_preserves_position_of_first_occurrence(self):
        h = MutableHeaders([(b"x-a", b"1"), (b"x-test", b"old"), (b"x-b", b"2")])
        h.set("x-test", "new")
        assert h.keys() == ["x-a", "x-test", "x-b"]

    def test_set_rejects_cr_in_key(self):
        h = MutableHeaders([])
        with pytest.raises(ValueError, match="Header name"):
            h.set("bad\rkey", "val")

    def test_set_rejects_lf_in_value(self):
        h = MutableHeaders([])
        with pytest.raises(ValueError, match="Header value"):
            h.set("x-test", "bad\nvalue")

    # -- append --

    def test_append_adds_duplicate_key(self):
        h = MutableHeaders([])
        h.append("set-cookie", "a=1")
        h.append("set-cookie", "b=2")
        assert h.getlist("set-cookie") == ["a=1", "b=2"]

    def test_append_preserves_existing(self):
        h = MutableHeaders([(b"x-a", b"1")])
        h.append("x-b", "2")
        assert h["x-a"] == "1"
        assert h["x-b"] == "2"

    def test_append_rejects_cr_in_key(self):
        h = MutableHeaders([])
        with pytest.raises(ValueError, match="Header name"):
            h.append("bad\rkey", "val")

    def test_append_rejects_lf_in_value(self):
        h = MutableHeaders([])
        with pytest.raises(ValueError, match="Header value"):
            h.append("x-test", "bad\nvalue")

    # -- delete --

    def test_delete_removes_key(self):
        h = MutableHeaders([(b"x-test", b"val")])
        h.delete("x-test")
        assert "x-test" not in h

    def test_delete_removes_all_occurrences(self):
        h = MutableHeaders([(b"x-test", b"a"), (b"x-test", b"b")])
        h.delete("x-test")
        assert "x-test" not in h
        assert h.getlist("x-test") == []

    def test_delete_missing_no_error(self):
        h = MutableHeaders([])
        h.delete("missing")

    def test_delete_preserves_other_keys(self):
        h = MutableHeaders([(b"x-a", b"1"), (b"x-test", b"val"), (b"x-b", b"2")])
        h.delete("x-test")
        assert h.keys() == ["x-a", "x-b"]

    # -- __setitem__ --

    def test_setitem_delegates_to_set(self):
        h = MutableHeaders([])
        h["x-test"] = "val"
        assert h["x-test"] == "val"

    def test_setitem_replaces_existing(self):
        h = MutableHeaders([(b"x-test", b"old")])
        h["x-test"] = "new"
        assert h["x-test"] == "new"

    # -- raw after mutations --

    def test_raw_reflects_set(self):
        h = MutableHeaders([(b"x-test", b"old")])
        h.set("x-test", "new")
        assert (b"x-test", b"new") in h.raw

    def test_raw_reflects_append(self):
        h = MutableHeaders([])
        h.append("x-test", "val")
        assert (b"x-test", b"val") in h.raw

    def test_raw_reflects_delete(self):
        h = MutableHeaders([(b"x-test", b"val")])
        h.delete("x-test")
        assert len(h.raw) == 0


class TestQueryParams:
    # -- basic parsing --

    def test_basic_parsing(self):
        q = QueryParams("a=1&b=2")
        assert q["a"] == "1"
        assert q["b"] == "2"

    def test_empty_string(self):
        q = QueryParams("")
        assert len(q) == 0
        assert list(q) == []

    def test_blank_values(self):
        q = QueryParams("a=&b=")
        assert q["a"] == ""
        assert q["b"] == ""

    def test_url_encoded_keys(self):
        q = QueryParams("my+key=1&my%20key=2")
        assert q.getlist("my key") == ["1", "2"]

    def test_url_encoded_values(self):
        q = QueryParams("q=hello+world&x=a%20b")
        assert q["q"] == "hello world"
        assert q["x"] == "a b"

    def test_special_characters(self):
        q = QueryParams("email=user%40example.com")
        assert q["email"] == "user@example.com"

    def test_no_equals_sign(self):
        q = QueryParams("flag")
        assert "flag" in q

    # -- multi-values --

    def test_multi_values(self):
        q = QueryParams("a=1&a=2&a=3")
        assert q.getlist("a") == ["1", "2", "3"]
        assert q.get("a") == "1"

    def test_get_returns_first_value(self):
        q = QueryParams("a=first&a=second")
        assert q.get("a") == "first"

    # -- get / getitem --

    def test_get_default(self):
        q = QueryParams("")
        assert q.get("missing", "default") == "default"

    def test_get_missing_returns_none(self):
        q = QueryParams("")
        assert q.get("missing") is None

    def test_getitem_missing_raises_keyerror(self):
        q = QueryParams("")
        with pytest.raises(KeyError):
            q["missing"]

    # -- __contains__ --

    def test_contains(self):
        q = QueryParams("a=1")
        assert "a" in q
        assert "b" not in q

    # -- __iter__ / __len__ --

    def test_iter_unique_keys(self):
        q = QueryParams("a=1&a=2&b=3")
        assert list(q) == ["a", "b"]

    def test_len_unique_keys(self):
        q = QueryParams("a=1&a=2&b=3")
        assert len(q) == 2

    def test_len_empty(self):
        q = QueryParams("")
        assert len(q) == 0

    # -- items / multi_items / keys --

    def test_items_deduped(self):
        q = QueryParams("a=1&a=2")
        assert q.items() == [("a", "1")]

    def test_multi_items(self):
        q = QueryParams("a=1&a=2")
        assert q.multi_items() == [("a", "1"), ("a", "2")]

    def test_keys_deduped(self):
        q = QueryParams("a=1&a=2&b=3")
        assert q.keys() == ["a", "b"]

    def test_keys_empty(self):
        q = QueryParams("")
        assert q.keys() == []

    # -- repr --

    def test_repr(self):
        q = QueryParams("a=1")
        assert "QueryParams" in repr(q)


class TestImmutableMultiDict:
    # -- basic access --

    def test_basic(self):
        d = ImmutableMultiDict([("a", "1"), ("b", "2")])
        assert d["a"] == "1"
        assert d["b"] == "2"

    def test_getitem_missing_raises_keyerror(self):
        d = ImmutableMultiDict([])
        with pytest.raises(KeyError):
            d["missing"]

    def test_get_existing(self):
        d = ImmutableMultiDict([("a", "1")])
        assert d.get("a") == "1"

    def test_get_missing_returns_none(self):
        d = ImmutableMultiDict([])
        assert d.get("missing") is None

    def test_get_custom_default(self):
        d = ImmutableMultiDict([])
        assert d.get("missing", "fallback") == "fallback"

    # -- multi-values --

    def test_getlist(self):
        d = ImmutableMultiDict([("a", "1"), ("a", "2")])
        assert d.getlist("a") == ["1", "2"]

    def test_getlist_missing_returns_empty(self):
        d = ImmutableMultiDict([])
        assert d.getlist("missing") == []

    def test_getlist_single_value(self):
        d = ImmutableMultiDict([("a", "1")])
        assert d.getlist("a") == ["1"]

    # -- __contains__ --

    def test_contains(self):
        d = ImmutableMultiDict([("a", "1")])
        assert "a" in d
        assert "b" not in d

    # -- __iter__ / __len__ --

    def test_iter_unique(self):
        d = ImmutableMultiDict([("a", "1"), ("a", "2"), ("b", "3")])
        assert list(d) == ["a", "b"]

    def test_len_unique_keys(self):
        d = ImmutableMultiDict([("a", "1"), ("a", "2"), ("b", "3")])
        assert len(d) == 2

    def test_len_empty(self):
        d = ImmutableMultiDict([])
        assert len(d) == 0

    # -- items / multi_items --

    def test_items_deduped(self):
        d = ImmutableMultiDict([("a", "1"), ("a", "2")])
        assert d.items() == [("a", "1")]

    def test_items_preserves_first_value(self):
        d = ImmutableMultiDict([("a", "first"), ("a", "second")])
        assert d.items() == [("a", "first")]

    def test_multi_items(self):
        d = ImmutableMultiDict([("a", "1"), ("a", "2")])
        assert d.multi_items() == [("a", "1"), ("a", "2")]

    def test_multi_items_empty(self):
        d = ImmutableMultiDict([])
        assert d.multi_items() == []

    # -- mixed types (str + UploadFile) --

    def test_mixed_str_and_upload_file(self):
        upload = UploadFile(filename="test.txt", content_type="text/plain", file=io.BytesIO(b"hi"))
        d = ImmutableMultiDict([("name", "alice"), ("file", upload)])
        assert d["name"] == "alice"
        assert isinstance(d["file"], UploadFile)

    def test_getlist_mixed_types(self):
        upload = UploadFile(filename="test.txt", content_type="text/plain", file=io.BytesIO(b"hi"))
        d = ImmutableMultiDict([("file", "readme.txt"), ("file", upload)])
        items = d.getlist("file")
        assert len(items) == 2
        assert items[0] == "readme.txt"
        assert isinstance(items[1], UploadFile)

    def test_contains_with_upload_file(self):
        upload = UploadFile(filename="test.txt", content_type="text/plain", file=io.BytesIO(b"hi"))
        d = ImmutableMultiDict([("file", upload)])
        assert "file" in d

    # -- repr --

    def test_repr(self):
        d = ImmutableMultiDict([("a", "1")])
        assert "ImmutableMultiDict" in repr(d)

    def test_repr_empty(self):
        d = ImmutableMultiDict([])
        assert "ImmutableMultiDict" in repr(d)
