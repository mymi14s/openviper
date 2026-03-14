"""Unit tests for openviper.utils.importlib — import_string and cache."""

from openviper.http.response import Response
from openviper.utils.importlib import _IMPORT_CACHE, import_string, reset_import_cache
from openviper.utils.timezone import now


class TestImportString:
    def test_imports_class(self):
        """L29-31: import_string resolves a dotted path to a class."""
        cls = import_string("openviper.http.response.Response")
        assert cls is Response

    def test_imports_function(self):
        func = import_string("openviper.utils.timezone.now")
        assert func is now

    def test_caching(self):
        """Same dotted path should return the same object (dict-cached)."""
        reset_import_cache()
        cls1 = import_string("openviper.http.response.Response")
        cls2 = import_string("openviper.http.response.Response")
        assert cls1 is cls2


class TestResetImportCache:
    def test_clears_cache(self):
        """L11: reset_import_cache clears _IMPORT_CACHE dict."""
        _IMPORT_CACHE["test_key"] = "test_value"
        reset_import_cache()
        assert "test_key" not in _IMPORT_CACHE
