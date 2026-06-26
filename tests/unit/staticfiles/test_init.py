"""Unit tests for openviper.staticfiles - static/media file serving flags."""

import openviper.staticfiles as sf_mod
from openviper.staticfiles import (
    is_media_enabled,
    is_static_enabled,
    media,
    static,
)


class TestStaticFunction:
    def test_returns_empty_list(self):
        result = static()
        assert result == []

    def test_enables_static_flag(self):
        sf_mod.static_serving_enabled.clear()
        static()
        assert sf_mod.static_serving_enabled.is_set() is True

    def test_is_static_enabled(self):
        sf_mod.static_serving_enabled.set()
        assert is_static_enabled() is True
        sf_mod.static_serving_enabled.clear()
        assert is_static_enabled() is False


class TestMediaFunction:
    def test_returns_empty_list(self):
        result = media()
        assert result == []

    def test_enables_media_flag(self):
        sf_mod.media_serving_enabled.clear()
        media()
        assert sf_mod.media_serving_enabled.is_set() is True

    def test_is_media_enabled(self):
        sf_mod.media_serving_enabled.set()
        assert is_media_enabled() is True
        sf_mod.media_serving_enabled.clear()
        assert is_media_enabled() is False
