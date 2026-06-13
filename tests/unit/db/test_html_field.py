"""Unit tests for HTMLField XSS sanitization and validation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openviper.db.fields import (
    DEFAULT_ALLOWED_ATTRIBUTES,
    DEFAULT_ALLOWED_SCHEMES,
    DEFAULT_ALLOWED_TAGS,
    HTMLField,
)


class TestHTMLFieldDefaultConfiguration:
    """HTMLField defaults match the module-level constants."""

    def test_default_allowed_tags(self):
        field = HTMLField()
        assert field.allowed_tags == DEFAULT_ALLOWED_TAGS

    def test_default_allowed_attributes(self):
        field = HTMLField()
        assert field.allowed_attributes == DEFAULT_ALLOWED_ATTRIBUTES

    def test_default_allowed_schemes(self):
        field = HTMLField()
        assert field.allowed_schemes == DEFAULT_ALLOWED_SCHEMES

    def test_strip_comments_defaults_to_true(self):
        field = HTMLField()
        assert field.strip_comments is True

    def test_column_type_is_text(self):
        field = HTMLField()
        assert field.column_type == "TEXT"


class TestHTMLFieldCustomConfiguration:
    """HTMLField accepts custom allowed tags, attributes, and schemes."""

    def test_custom_allowed_tags(self):
        tags = frozenset({"b", "i"})
        field = HTMLField(allowed_tags=tags)
        assert field.allowed_tags == tags

    def test_custom_allowed_attributes(self):
        attrs = {"a": frozenset({"href"})}
        field = HTMLField(allowed_attributes=attrs)
        assert field.allowed_attributes == attrs

    def test_custom_allowed_schemes(self):
        schemes = frozenset({"https"})
        field = HTMLField(allowed_schemes=schemes)
        assert field.allowed_schemes == schemes

    def test_strip_comments_can_be_disabled(self):
        field = HTMLField(strip_comments=False)
        assert field.strip_comments is False


class TestHTMLFieldSanitizationWithNh3:
    """HTMLField.sanitize strips dangerous markup using nh3."""

    def test_script_tags_removed(self):
        field = HTMLField()
        assert field.sanitize("<script>alert(1)</script><p>ok</p>") == "<p>ok</p>"

    def test_allowed_tags_preserved(self):
        field = HTMLField()
        assert field.sanitize("<p>Hello</p>") == "<p>Hello</p>"

    def test_disallowed_tags_stripped(self):
        field = HTMLField()
        assert field.sanitize("<div><p>Hello</p></div>") == "<p>Hello</p>"

    def test_allowed_attributes_preserved(self):
        field = HTMLField()
        result = field.sanitize('<a href="https://example.com" title="x">link</a>')
        assert 'href="https://example.com"' in result
        assert 'title="x"' in result
        assert "<a" in result
        assert ">link</a>" in result

    def test_javascript_scheme_removed(self):
        field = HTMLField()
        assert "javascript" not in field.sanitize('<a href="javascript:alert(1)">x</a>').lower()

    def test_comments_stripped_by_default(self):
        field = HTMLField()
        assert field.sanitize("<!-- comment --><p>x</p>") == "<p>x</p>"

    def test_comments_preserved_when_disabled(self):
        field = HTMLField(strip_comments=False)
        assert "comment" in field.sanitize("<!-- comment --><p>x</p>")

    def test_nesting_allowed_tags(self):
        field = HTMLField()
        assert (
            field.sanitize("<p><strong><em>bold</em></strong></p>")
            == "<p><strong><em>bold</em></strong></p>"
        )

    def test_custom_allowed_tags_override_defaults(self):
        field = HTMLField(allowed_tags=frozenset({"b"}))
        assert field.sanitize("<p><b>x</b></p>") == "<b>x</b>"

    def test_empty_string_returns_empty(self):
        field = HTMLField()
        assert field.sanitize("") == ""


class TestHTMLFieldToPython:
    """HTMLField.to_python sanitizes input and handles None."""

    def test_none_returns_none(self):
        field = HTMLField()
        assert field.to_python(None) is None

    def test_string_is_sanitized(self):
        field = HTMLField()
        assert field.to_python("<script></script><p>a</p>") == "<p>a</p>"

    def test_non_string_is_coerced(self):
        field = HTMLField()
        assert field.to_python(123) == "123"


class TestHTMLFieldValidation:
    """HTMLField.validate rejects non-string values."""

    def test_string_passes(self):
        field = HTMLField()
        field.validate("<p>ok</p>")

    def test_non_string_raises(self):
        field = HTMLField()
        with pytest.raises(ValueError, match="expected a string"):
            field.validate(123)

    def test_none_null_true(self):
        field = HTMLField(null=True)
        field.validate(None)

    def test_none_null_false(self):
        field = HTMLField(null=False)
        with pytest.raises(ValueError, match="cannot be null"):
            field.validate(None)


class TestHTMLFieldFallbackWithoutNh3:
    """When nh3 is unavailable, HTMLField falls back to html.escape."""

    def test_fallback_escapes_html(self):
        field = HTMLField()
        with patch("openviper.db.fields.nh3_lib", None):
            result = field.sanitize("<p>x</p>")
        assert "&lt;p&gt;x&lt;/p&gt;" in result

    def test_fallback_with_script(self):
        field = HTMLField()
        with patch("openviper.db.fields.nh3_lib", None):
            result = field.sanitize("<script>alert(1)</script>")
        assert "&lt;script&gt;" in result


class TestHTMLFieldSanitizeEdgeCases:
    """Edge-case inputs for HTMLField.sanitize."""

    def test_only_unsafe_input(self):
        field = HTMLField()
        assert field.sanitize("<script>alert(1)</script>") == ""

    def test_mixed_safe_and_unsafe(self):
        field = HTMLField()
        assert field.sanitize("<p>safe</p><iframe src=x></iframe>") == "<p>safe</p>"

    def test_attributes_on_disallowed_tag_removed(self):
        field = HTMLField()
        assert field.sanitize('<div class="x">text</div>') == "text"
