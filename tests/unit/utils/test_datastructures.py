import pytest

from openviper.utils.datastructures import Headers, ImmutableMultiDict, MutableHeaders, QueryParams


def test_headers_immutable():
    raw = [(b"Content-Type", b"application/json"), (b"X-Test", b"Value")]
    headers = Headers(raw)

    assert headers["content-type"] == "application/json"
    assert headers["X-TEST"] == "Value"

    with pytest.raises(KeyError):
        _ = headers["missing"]

    assert headers.get("content-type") == "application/json"
    assert headers.get("missing", "default") == "default"

    raw_multi = [(b"set-cookie", b"a=1"), (b"set-cookie", b"b=2")]
    multi_headers = Headers(raw_multi)
    assert multi_headers.getlist("set-cookie") == ["a=1", "b=2"]

    assert "Content-Type" in headers
    assert "missing" not in headers
    assert 123 not in headers

    assert list(headers.keys()) == ["content-type", "x-test"]
    assert list(headers.values()) == ["application/json", "Value"]
    assert list(headers.items()) == [("content-type", "application/json"), ("x-test", "Value")]
    assert len(headers) == 2
    assert list(iter(headers)) == ["content-type", "x-test"]
    assert repr(headers) == "Headers({'content-type': 'application/json', 'x-test': 'Value'})"
    assert headers.raw == [(b"content-type", b"application/json"), (b"x-test", b"Value")]


def test_headers_mutable():
    headers = MutableHeaders()
    headers.set("content-type", "text/plain")
    assert headers["content-type"] == "text/plain"

    headers["content-type"] = "application/json"
    assert headers["content-type"] == "application/json"

    headers.append("set-cookie", "a=1")
    headers.append("set-cookie", "b=2")
    assert headers.getlist("set-cookie") == ["a=1", "b=2"]

    headers.delete("content-type")
    assert "content-type" not in headers


def test_query_params():
    params = QueryParams("a=1&b=2&a=3&c=")
    assert params["a"] == "1"
    assert params["b"] == "2"
    assert params["c"] == ""

    with pytest.raises(KeyError):
        _ = params["missing"]

    assert params.get("a") == "1"
    assert params.get("missing", "def") == "def"

    assert params.getlist("a") == ["1", "3"]
    assert params.getlist("missing") == []

    assert "a" in params
    assert "missing" not in params

    assert list(iter(params)) == ["a", "b", "c"]
    assert len(params) == 3
    assert params.keys() == ["a", "b", "c"]

    items = params.items()
    assert ("a", "1") in items
    assert ("b", "2") in items

    multi = params.multi_items()
    assert ("a", "1") in multi
    assert ("a", "3") in multi

    assert repr(params) == "QueryParams([('a', '1'), ('b', '2'), ('c', '')])"


def test_immutable_multi_dict():
    imd = ImmutableMultiDict([("a", 1), ("b", 2), ("a", 3)])

    assert imd.get("a") == 1
    assert imd.get("missing", 99) == 99

    assert imd.getlist("a") == [1, 3]

    assert imd["b"] == 2
    with pytest.raises(KeyError):
        _ = imd["z"]

    assert "a" in imd
    assert "missing" not in imd

    assert list(iter(imd)) == ["a", "b"]
    assert len(imd) == 2

    items = imd.items()
    assert items == [("a", 1), ("b", 2)]

    multi = imd.multi_items()
    assert multi == [("a", 1), ("b", 2), ("a", 3)]

    assert repr(imd) == "ImmutableMultiDict([('a', 1), ('b', 2), ('a', 3)])"
