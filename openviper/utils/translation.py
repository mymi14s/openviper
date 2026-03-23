import gettext as gettext_module
from contextvars import ContextVar
from typing import Any

# Context storage for current language
_active_language: ContextVar[str] = ContextVar("active_language", default="en")

# Cache for translation objects
_translations_cache: dict[str, gettext_module.NullTranslations] = {}

# Default configuration
LOCALE_DIR = "locale"
DEFAULT_DOMAIN = "messages"


def get_language() -> str:
    """Get the current active language from the context."""
    return _active_language.get()


def set_language(language: str) -> None:
    """Set the active language for the current context."""
    _active_language.set(language)


def _get_translation_object(language: str) -> gettext_module.NullTranslations:
    """Retrieve or load a translation object for the given language."""
    if language not in _translations_cache:
        try:
            # Attempt to load binary .mo translations from locale directory
            # Structure: locale/{lang}/LC_MESSAGES/{domain}.mo
            translation = gettext_module.translation(
                domain=DEFAULT_DOMAIN,
                localedir=LOCALE_DIR,
                languages=[language],
                fallback=True,
            )
            _translations_cache[language] = translation
        except Exception:
            # Fallback to NullTranslations if directory or file is missing
            _translations_cache[language] = gettext_module.NullTranslations()

    return _translations_cache[language]


class LazyString:
    """A string that defers its translation until it's actually used."""

    def __init__(self, message: str):
        self._message = message

    def __str__(self) -> str:
        return gettext(self._message)

    def __repr__(self) -> str:
        return f"LazyString({self._message!r})"

    def __eq__(self, other: Any) -> bool:
        return str(self) == str(other)

    def __add__(self, other: Any) -> str:
        return str(self) + str(other)

    def __radd__(self, other: Any) -> str:
        return str(other) + str(self)

    def __mod__(self, other: Any) -> str:
        return str(self) % other

    def __bool__(self) -> bool:
        return bool(str(self))

    def __len__(self) -> int:
        return len(str(self))


def gettext(message: str) -> str:
    """Translate the message immediately using the active language."""
    if not message:
        return ""

    lang = get_language()
    translation = _get_translation_object(lang)
    return translation.gettext(message)


def gettext_lazy(message: str) -> LazyString:
    """Return a LazyString that will be translated when evaluated."""
    return LazyString(message)


# Alias for gettext_lazy to match Django convention
_ = gettext_lazy
