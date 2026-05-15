import gettext as gettext_module
from contextvars import ContextVar
from pathlib import Path

__all__ = [
    "LOCALE_DIR",
    "DEFAULT_DOMAIN",
    "get_language",
    "set_language",
    "gettext",
    "ngettext",
    "LazyString",
]

_active_language: ContextVar[str] = ContextVar("active_language", default="en")
_translations_cache: dict[str, gettext_module.NullTranslations] = {}
LOCALE_DIR: str = str(Path(__file__).resolve().parent.parent.parent / "locale")
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
            translation = gettext_module.translation(
                domain=DEFAULT_DOMAIN,
                localedir=LOCALE_DIR,
                languages=[language],
                fallback=True,
            )
            _translations_cache[language] = translation
        except OSError, ValueError:
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

    def __eq__(self, other: object) -> bool:
        return str(self) == str(other)

    def __add__(self, other: str) -> str:
        return str(self) + str(other)

    def __radd__(self, other: str) -> str:
        return str(other) + str(self)

    def __mod__(self, other: str | int | float | tuple) -> str:
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


def ngettext(singular: str, plural: str, n: int) -> str:
    """Translate a message with plural forms using the active language."""
    lang = get_language()
    translation = _get_translation_object(lang)
    return translation.ngettext(singular, plural, n)


def gettext_lazy(message: str) -> LazyString:
    """Return a LazyString that will be translated when evaluated."""
    return LazyString(message)


_ = gettext_lazy
