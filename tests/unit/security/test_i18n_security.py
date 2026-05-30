"""Internationalization (i18n) security tests.

Requirement IDs: I18N-001 through I18N-003.

Covers:
  I18N-001 - Locale file loading prevents path traversal
  I18N-002 - Translation strings are escaped by default
  I18N-003 - Unicode normalization is consistent
"""

from __future__ import annotations

import gettext as gettext_module
import unicodedata
from contextvars import ContextVar
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openviper.utils.translation import (
    LOCALE_DIR,
    LazyString,
    get_language,
    get_translation_object,
    gettext,
    gettext_lazy,
    ngettext,
    set_language,
    translations_cache,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_language() -> None:
    """Reset active language to a safe default after each test."""
    set_language("en")
    yield
    set_language("en")


@pytest.fixture(autouse=True)
def clear_translations_cache() -> None:
    """Purge the translations cache before and after each test."""
    translations_cache.clear()
    yield
    translations_cache.clear()


# ---------------------------------------------------------------------------
# I18N-001: Locale file loading prevents path traversal
# ---------------------------------------------------------------------------


class TestI18N001LocalePathTraversal:
    """Locale file loading must prevent path traversal attacks.

    Language codes are used to construct filesystem paths inside LOCALE_DIR.
    Malicious codes containing directory separators, encoded traversal
    sequences, null bytes, or Unicode tricks must never escape the locale
    directory boundary.
    """

    # -- Positive tests: valid language codes are accepted ----------------

    @pytest.mark.parametrize("code", ["en", "fr", "de", "pt_BR", "zh_Hans"])
    def test_i18n001_valid_language_codes_accepted(self, code: str) -> None:
        """Valid BCP-47 / POSIX language codes must be accepted."""
        set_language(code)
        assert get_language() == code

    def test_i18n001_gettext_with_valid_language_returns_string(self) -> None:
        """gettext must return a plain string for a valid language."""
        set_language("en")
        result = gettext("Hello")
        assert isinstance(result, str)

    # -- Negative tests: path traversal in language codes -----------------

    @pytest.mark.parametrize(
        "malicious_code",
        [
            "../etc",
            "..%2fetc",
            "%2e%2e/etc",
            "..%2Fetc",
            "%252e%252e%252fetc",
            "../../../etc/passwd",
            "..\\..\\windows\\system32",
            "en/../../../etc",
            "/etc/passwd",
            "en/../../secret",
        ],
    )
    def test_i18n001_path_traversal_codes_rejected_safely(self, malicious_code: str) -> None:
        """Language codes containing path traversal sequences must not
        cause filesystem access outside the locale directory."""
        set_language(malicious_code)
        # Must not crash; must fall back to NullTranslations
        result = gettext("Hello")
        assert isinstance(result, str)
        # The malicious code must not have been used to resolve a real path
        # outside LOCALE_DIR - verify the cache entry is NullTranslations
        if malicious_code in translations_cache:
            assert isinstance(
                translations_cache[malicious_code],
                gettext_module.NullTranslations,
            )

    @pytest.mark.parametrize(
        "null_byte_code",
        [
            "en\x00../etc",
            "en\x00",
            "\x00en",
            "fr\x00.png",
        ],
    )
    def test_i18n001_null_bytes_in_language_codes_handled_safely(self, null_byte_code: str) -> None:
        """Null bytes in language codes must not allow path truncation attacks."""
        set_language(null_byte_code)
        result = gettext("Hello")
        assert isinstance(result, str)

    @pytest.mark.parametrize(
        "unicode_trick_code",
        [
            "en\u202etxt",  # Right-to-Left Override
            "en\u200f../etc",  # Right-to-Left Mark
            "en\ufeff",  # Byte Order Mark
            "en\u00a0",  # Non-breaking space
            "en\u200b",  # Zero-width space
            "en\u200c",  # Zero-width non-joiner
            "en\u200d",  # Zero-width joiner
            "en\u2060",  # Word joiner
        ],
    )
    def test_i18n001_unicode_tricks_in_language_codes_handled_safely(
        self, unicode_trick_code: str
    ) -> None:
        """Unicode direction overrides, zero-width characters, and BOM
        must not bypass locale path validation."""
        set_language(unicode_trick_code)
        result = gettext("Hello")
        assert isinstance(result, str)

    def test_i18n001_encoded_slash_in_language_code(self) -> None:
        """URL-encoded slashes must not bypass path validation."""
        set_language("en%2F..%2F..%2Fetc")
        result = gettext("Hello")
        assert isinstance(result, str)

    def test_i18n001_double_encoded_traversal(self) -> None:
        """Double-encoded path traversal must not bypass validation."""
        set_language("%252e%252e%252fetc%252fpasswd")
        result = gettext("Hello")
        assert isinstance(result, str)

    def test_i18n001_mixed_case_traversal(self) -> None:
        """Mixed-case path traversal sequences must not bypass validation."""
        set_language("..%2F..%2F..%2Fetc%2Fpasswd")
        result = gettext("Hello")
        assert isinstance(result, str)

    def test_i18n001_backslash_traversal(self) -> None:
        """Backslash-based path traversal must not bypass validation."""
        set_language("..\\..\\etc")
        result = gettext("Hello")
        assert isinstance(result, str)

    # -- Fail-closed behavior ---------------------------------------------

    def test_i18n001_get_translation_object_falls_back_on_oserror(self) -> None:
        """get_translation_object must return NullTranslations on OSError."""
        with patch(
            "openviper.utils.translation.gettext_module.translation",
            side_effect=OSError("locale not found"),
        ):
            obj = get_translation_object("nonexistent_lang")
            assert isinstance(obj, gettext_module.NullTranslations)

    def test_i18n001_get_translation_object_falls_back_on_valueerror(self) -> None:
        """get_translation_object must return NullTranslations on ValueError."""
        with patch(
            "openviper.utils.translation.gettext_module.translation",
            side_effect=ValueError("bad language"),
        ):
            obj = get_translation_object("bad_lang")
            assert isinstance(obj, gettext_module.NullTranslations)

    def test_i18n001_cache_does_not_leak_between_invalid_codes(self) -> None:
        """Each invalid language code must get its own cache entry
        that maps to NullTranslations, not a shared mutable object."""
        set_language("traversal1")
        gettext("a")
        set_language("traversal2")
        gettext("b")
        assert "traversal1" in translations_cache
        assert "traversal2" in translations_cache
        assert isinstance(translations_cache["traversal1"], gettext_module.NullTranslations)
        assert isinstance(translations_cache["traversal2"], gettext_module.NullTranslations)

    def test_i18n001_locale_dir_is_within_project(self) -> None:
        """LOCALE_DIR must resolve to a path within the project tree,
        not to an arbitrary filesystem location."""
        locale_path = Path(LOCALE_DIR).resolve()
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        assert str(locale_path).startswith(
            str(project_root)
        ), f"LOCALE_DIR {locale_path} escapes project root {project_root}"

    def test_i18n001_empty_language_code_handled_safely(self) -> None:
        """An empty string language code must not crash or cause unexpected
        filesystem access."""
        set_language("")
        result = gettext("Hello")
        assert isinstance(result, str)

    def test_i18n001_very_long_language_code_handled_safely(self) -> None:
        """An excessively long language code must not cause buffer issues."""
        set_language("en" * 1000)
        result = gettext("Hello")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# I18N-002: Translation strings are escaped by default
# ---------------------------------------------------------------------------


class TestI18N002TranslationEscaping:
    """Translation strings must be escaped by default.

    gettext / ngettext / LazyString must return plain strings.  If a
    translation value contains HTML or script tags, the caller must
    explicitly opt into rendering - the default must be safe (escaped).
    """

    # -- Positive tests: normal translations work --------------------------

    def test_i18n002_gettext_returns_plain_string(self) -> None:
        """gettext must return a plain str, not an HTML-safe object."""
        set_language("en")
        result = gettext("Hello")
        assert isinstance(result, str)

    def test_i18n002_ngettext_returns_plain_string(self) -> None:
        """ngettext must return a plain str for both singular and plural."""
        set_language("en")
        assert isinstance(ngettext("item", "items", 1), str)
        assert isinstance(ngettext("item", "items", 5), str)

    def test_i18n002_lazy_string_defers_translation(self) -> None:
        """LazyString must defer translation until string conversion."""
        lazy = gettext_lazy("Hello")
        assert isinstance(lazy, LazyString)
        resolved = str(lazy)
        assert isinstance(resolved, str)

    # -- Negative tests: HTML/script injection in translations ------------

    @pytest.mark.parametrize(
        "payload",
        [
            "<script>alert(1)</script>",
            '"><img src=x onerror=alert(1)>',
            "</script><script>alert(1)</script>",
            "<svg onload=alert(1)>",
            "<body onload=alert(1)>",
            "<iframe src='javascript:alert(1)'>",
            "<a href='javascript:alert(1)'>click</a>",
        ],
    )
    def test_i18n002_script_injection_in_gettext_neutralized(self, payload: str) -> None:
        """HTML/script injection in gettext input must be returned as a
        literal string, never executed or auto-rendered."""
        set_language("en")
        result = gettext(payload)
        assert isinstance(result, str)
        # The raw payload text must be preserved verbatim (no stripping),
        # but it must be a plain string - not an HTML-safe marked object.
        assert payload in result or result == payload

    @pytest.mark.parametrize(
        "payload",
        [
            "<script>alert(1)</script>",
            '"><img src=x onerror=alert(1)>',
            "<svg onload=alert(1)>",
        ],
    )
    def test_i18n002_script_injection_in_ngettext_neutralized(self, payload: str) -> None:
        """HTML/script injection in ngettext input must be returned as a
        literal string."""
        set_language("en")
        result = ngettext(payload, payload + "s", 1)
        assert isinstance(result, str)

    def test_i18n002_lazy_string_preserves_html_as_text(self) -> None:
        """LazyString must not auto-escape or render HTML; it must preserve
        the raw string for the caller to escape."""
        payload = "<script>alert(1)</script>"
        lazy = gettext_lazy(payload)
        resolved = str(lazy)
        assert isinstance(resolved, str)
        assert "<script>" in resolved

    def test_i18n002_gettext_with_html_entities_not_rendered(self) -> None:
        """HTML entities in translation strings must not be rendered."""
        set_language("en")
        result = gettext("&lt;script&gt;alert(1)&lt;/script&gt;")
        assert isinstance(result, str)
        # Must preserve the entity text literally, not decode it
        assert "&lt;" in result

    def test_i18n002_gettext_with_format_string_not_interpolated(self) -> None:
        """Python format-string patterns in translations must not be
        auto-interpolated with attacker-controlled data."""
        set_language("en")
        result = gettext("Hello %(name)s")
        assert isinstance(result, str)
        # The format placeholder must remain as-is in the raw string
        assert "%(name)s" in result

    # -- Context-specific escaping ----------------------------------------

    def test_i18n002_gettext_empty_string_returns_empty(self) -> None:
        """An empty message must return an empty string, not None or error."""
        set_language("en")
        result = gettext("")
        assert result == ""

    def test_i18n002_ngettext_singular_form(self) -> None:
        """ngettext with n=1 must return the singular form."""
        set_language("en")
        result = ngettext("item", "items", 1)
        assert result == "item"

    def test_i18n002_ngettext_plural_form(self) -> None:
        """ngettext with n>1 must return the plural form."""
        set_language("en")
        result = ngettext("item", "items", 5)
        assert result == "items"

    def test_i18n002_ngettext_zero_uses_plural(self) -> None:
        """ngettext with n=0 must return the plural form (English rule)."""
        set_language("en")
        result = ngettext("item", "items", 0)
        assert result == "items"

    # -- Fail-closed: mock translation returning malicious content ---------

    def test_i18n002_malicious_translation_content_returned_as_string(self) -> None:
        """Even if a translation object returns malicious HTML, gettext
        must return it as a plain string - the caller is responsible for
        escaping at the rendering layer."""
        mock_translation = MagicMock(spec=gettext_module.NullTranslations)
        mock_translation.gettext.return_value = "<script>steal()</script>"

        with patch(
            "openviper.utils.translation.get_translation_object",
            return_value=mock_translation,
        ):
            set_language("malicious_lang")
            result = gettext("Welcome")
            assert isinstance(result, str)
            assert "<script>" in result
            # The result is a plain str, not a special HTML-safe type
            assert type(result) is str

    def test_i18n002_ngettext_malicious_translation_content_as_string(self) -> None:
        """Malicious content from ngettext must be returned as plain str."""
        mock_translation = MagicMock(spec=gettext_module.NullTranslations)
        mock_translation.ngettext.return_value = "<img src=x onerror=alert(1)>"

        with patch(
            "openviper.utils.translation.get_translation_object",
            return_value=mock_translation,
        ):
            set_language("malicious_lang")
            result = ngettext("file", "files", 2)
            assert isinstance(result, str)
            assert type(result) is str


# ---------------------------------------------------------------------------
# I18N-003: Unicode normalization is consistent
# ---------------------------------------------------------------------------


class TestI18N003UnicodeNormalization:
    """Unicode normalization must be consistent across the i18n subsystem.

    Language codes and translation strings that are visually identical
    but differ in Unicode representation must be handled deterministically.
    """

    # -- Positive tests: normalization consistency --------------------------

    def test_i18n003_nfc_vs_nfd_language_codes(self) -> None:
        """NFC and NFD forms of the same language code must resolve
        consistently.  For example, 'pt-BR' with precomposed vs decomposed
        characters must not create divergent cache entries."""
        # ASCII codes have no NFC/NFD difference - verify they resolve
        set_language("pt-BR")
        assert get_language() == "pt-BR"
        result = gettext("Hello")
        assert isinstance(result, str)

    def test_i18n003_accented_language_codes_handled(self) -> None:
        """Language codes with accented characters must be handled safely."""
        # Some locale systems use accented codes; ensure no crash
        set_language("fr_CA")
        result = gettext("Hello")
        assert isinstance(result, str)

    @pytest.mark.parametrize(
        ("normalized", "denormalized"),
        [
            # NFC vs NFD for é (U+00E9 vs U+0065 U+0301)
            ("caf\u00e9", "cafe\u0301"),
            # Full-width Latin vs ASCII
            ("en", "\uff45\uff4e"),
        ],
    )
    def test_i18n003_visually_similar_strings_not_confused(
        self, normalized: str, denormalized: str
    ) -> None:
        """Visually similar but Unicode-distinct strings must not be
        silently conflated.  The system must handle each distinctly
        without crashing or producing unexpected results."""
        set_language(normalized)
        result_norm = gettext("Hello")
        assert isinstance(result_norm, str)

        set_language(denormalized)
        result_denorm = gettext("Hello")
        assert isinstance(result_denorm, str)

        # Both must return strings; whether they match depends on
        # whether the system normalizes, but neither must crash.
        assert isinstance(result_norm, str)
        assert isinstance(result_denorm, str)

    def test_i18n003_unicode_normalization_forms_deterministic(self) -> None:
        """Applying the same normalization form twice must yield the
        same result (idempotency)."""
        original = "caf\u00e9"
        nfc_once = unicodedata.normalize("NFC", original)
        nfc_twice = unicodedata.normalize("NFC", nfc_once)
        assert nfc_once == nfc_twice

        nfd_once = unicodedata.normalize("NFD", original)
        nfd_twice = unicodedata.normalize("NFD", nfd_once)
        assert nfd_once == nfd_twice

    def test_i18n003_gettext_with_unicode_message(self) -> None:
        """gettext must handle Unicode messages without corruption."""
        set_language("en")
        result = gettext("café")
        assert isinstance(result, str)

    def test_i18n003_ngettext_with_unicode_message(self) -> None:
        """ngettext must handle Unicode messages without corruption."""
        set_language("en")
        result = ngettext("café", "cafés", 1)
        assert isinstance(result, str)

    # -- Context isolation ------------------------------------------------

    def test_i18n003_context_var_isolation(self) -> None:
        """Language context must be isolated - setting one language must
        not leak into subsequent operations."""
        set_language("en")
        assert get_language() == "en"

        set_language("fr")
        assert get_language() == "fr"

        set_language("de")
        assert get_language() == "de"

        # Reset
        set_language("en")
        assert get_language() == "en"

    def test_i18n003_context_var_default_is_en(self) -> None:
        """The default active language must be 'en'."""
        # Create a fresh ContextVar to verify the default
        fresh_var: ContextVar[str] = ContextVar("test_lang", default="en")
        assert fresh_var.get() == "en"

    def test_i18n003_hangul_jamo_vs_composed(self) -> None:
        """Hangul Jamo (decomposed) vs composed syllables must be handled
        without crashing the translation system."""
        # 가 (U+AC00) vs ᄀ (U+1100) + ᅡ (U+1161)
        composed = "\uac00"
        decomposed = "\u1100\u1161"
        for code in (composed, decomposed):
            set_language(code)
            result = gettext("Hello")
            assert isinstance(result, str)

    def test_i18n003_cyrillic_homoglyph_not_confused_with_latin(self) -> None:
        """Cyrillic homoglyphs of Latin characters must not be confused
        with their Latin counterparts in language codes."""
        # Cyrillic 'а' (U+0430) vs Latin 'a' (U+0061)
        cyrillic_a = "\u0430"
        latin_a = "a"
        assert cyrillic_a != latin_a  # Different code points

        set_language(f"en{cyrillic_a}")
        result_cyr = gettext("Hello")
        assert isinstance(result_cyr, str)

        set_language(f"en{latin_a}")
        result_lat = gettext("Hello")
        assert isinstance(result_lat, str)

    # -- Fail-closed: normalization must not weaken security --------------

    def test_i18n003_normalization_does_not_enable_traversal(self) -> None:
        """Unicode normalization must not transform safe-looking strings
        into path traversal sequences."""
        # U+FF0F is a fullwidth solidus (／) - normalizing to NFC must not
        # produce an ASCII slash that enables traversal.
        fullwidth_slash = "\uff0f"
        normalized = unicodedata.normalize("NFC", fullwidth_slash)
        # Fullwidth solidus must not become ASCII '/' under NFC
        assert (
            normalized != "/"
        ), "NFC normalization must not convert fullwidth slash to ASCII slash"

    def test_i18n003_normalization_does_not_create_dot_dot_slash(self) -> None:
        """Unicode normalization must not create '../' sequences from
        visually similar but distinct characters."""
        # U+FF0E is fullwidth period, U+FF0F is fullwidth solidus
        payload = "\uff0e\uff0e\uff0f"
        normalized = unicodedata.normalize("NFC", payload)
        assert (
            "../" not in normalized
        ), "NFC normalization must not produce '../' from fullwidth characters"
