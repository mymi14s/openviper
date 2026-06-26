"""Money value object extending py-moneyed for openviper integration.

Subclasses py-moneyed's Money to add decimal_places tracking and
locale-aware string formatting via babel (a py-moneyed dependency).
"""

from __future__ import annotations

from decimal import Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from babel.numbers import format_currency as babel_format_currency
from babel.numbers import get_currency_symbol as babel_get_currency_symbol
from moneyed import Currency as BaseCurrency
from moneyed import Money as BaseMoney
from moneyed.l10n import format_money

from openviper.contrib.fields.currencies.amount_in_words import convert_amount_to_words

if TYPE_CHECKING:
    from collections.abc import Mapping

    from openviper.contrib.fields.currencies.types import FormatOptions

DEFAULT_DECIMAL_PLACES: int = 2
DEFAULT_LOCALE: str = "en_US"

currency_symbol_cache: dict[str, str | None] = {}


def currency_symbol(self: BaseCurrency) -> str | None:
    """Return the babel locale symbol for this currency, or None."""
    code = self.code
    if not code:
        return None
    if code in currency_symbol_cache:
        return currency_symbol_cache[code]
    try:
        symbol = cast("str", babel_get_currency_symbol(code, locale=DEFAULT_LOCALE))
    except (KeyError, ValueError, LookupError):
        symbol = None
    currency_symbol_cache[code] = symbol
    return symbol


BaseCurrency.symbol = property(currency_symbol)


class Money(BaseMoney):
    """Monetary amount paired with an ISO 4217 currency.

    Extends py-moneyed.Money with decimal_places tracking for consistent
    storage precision and deterministic string formatting.
    """

    bound_field: object | None = None
    bound_instance: object | None = None

    def __init__(
        self,
        amount: object = 0,
        currency: str | BaseCurrency | None = None,
        *,
        decimal_places: int = DEFAULT_DECIMAL_PLACES,
        format_options: FormatOptions | None = None,
    ) -> None:
        if currency is None:
            raise TypeError("currency is required")
        if amount is None:
            raise TypeError("amount cannot be None; use 0 or a numeric value")
        super().__init__(amount, currency)
        self.decimal_places: int = decimal_places
        self.format_options: MappingProxyType[str, object] | None = (
            MappingProxyType(format_options) if format_options is not None else None
        )

    def set_format_options(
        self,
        *,
        locale: str | None = None,
        decimal_quantization: bool | None = None,
        currency_digits: bool | None = None,
        **extra: object,
    ) -> None:
        """Set formatting options that persist across attribute accesses.

        Accepts the following keyword arguments plus any additional
        options that babel's ``format_money`` supports:

        - ``locale`` - Babel locale string (e.g. ``"de_DE"``, ``"fr_FR"``)
        - ``decimal_quantization`` - Pad/truncate to locale decimal places
        - ``currency_digits`` - Use the currency's official decimal places
        - ``**extra`` - Any additional babel ``format_money`` options

        When called on a Money retrieved from a model field
        (``obj.price.set_format_options(locale="de_DE")``), the options
        are stored on the model instance so subsequent ``obj.price``
        accesses preserve them.

        When called on a standalone Money, only this instance is affected.

        .. code-block:: python

           product = await Product.objects.get(id=1)
           product.price.set_format_options(locale="de_DE")
           product.price.formatted_currency  # "1.234,56 €"

           # Multiple options at once
           product.price.set_format_options(
               locale="fr_FR",
               decimal_quantization=False,
           )

           # Reset to default
           product.price.set_format_options(locale="en_US")
        """
        opts: dict[str, object] = {}
        if self.format_options is not None:
            opts = dict(self.format_options)
        if locale is not None:
            opts["locale"] = locale
        if decimal_quantization is not None:
            opts["decimal_quantization"] = decimal_quantization
        if currency_digits is not None:
            opts["currency_digits"] = currency_digits
        opts.update(extra)

        field = getattr(self, "bound_field", None)
        instance = getattr(self, "bound_instance", None)
        if field is not None and instance is not None:
            field.set_format_options(instance, opts if opts else None)
        else:
            self.format_options = (
                MappingProxyType(opts) if opts else None
            )

    def copy_attributes(self, source: BaseMoney | object, target: BaseMoney) -> None:
        """Preserve decimal_places across arithmetic results."""
        candidates: list[int | None] = [
            getattr(self, "decimal_places", None),
            getattr(source, "decimal_places", None),
        ]
        selected = [c for c in candidates if c is not None]
        if selected:
            target.decimal_places = max(selected)

    def __add__(self, other: object) -> Money:
        result = super().__add__(other)
        if result is NotImplemented:
            return NotImplemented
        if isinstance(other, Money):
            self.copy_attributes(other, result)
        else:
            self.copy_attributes(self, result)
        return result

    def __sub__(self, other: object) -> Money:
        if isinstance(other, BaseMoney):
            result = super().__sub__(other)
        elif isinstance(other, (int, float, Decimal)):
            negated = self.__class__(Decimal(str(-other)), self.currency)
            result = super().__add__(negated)
        else:
            result = NotImplemented
        if result is NotImplemented:
            return NotImplemented
        if isinstance(other, Money):
            self.copy_attributes(other, result)
        else:
            self.copy_attributes(self, result)
        return result

    def __mul__(self, other: object) -> Money:
        result = super().__mul__(other)
        if result is NotImplemented:
            return NotImplemented
        if isinstance(other, Money):
            self.copy_attributes(other, result)
        else:
            self.copy_attributes(self, result)
        return result

    def __truediv__(self, other: object) -> Money | Decimal:
        result = super().__truediv__(other)
        if result is NotImplemented:
            return NotImplemented
        if isinstance(result, Money):
            if isinstance(other, Money):
                self.copy_attributes(other, result)
            else:
                self.copy_attributes(self, result)
        return result

    def __round__(self, n: int | None = None) -> Money:
        rounded = super().round(n if n is not None else 0)
        self.copy_attributes(self, rounded)
        return rounded

    def round(self, ndigits: int = 0) -> Money:
        rounded = super().round(ndigits)
        self.copy_attributes(self, rounded)
        return rounded

    def __pos__(self) -> Money:
        result = super().__pos__()
        self.copy_attributes(self, result)
        return result

    def __neg__(self) -> Money:
        result = super().__neg__()
        self.copy_attributes(self, result)
        return result

    def __abs__(self) -> Money:
        result = super().__abs__()
        self.copy_attributes(self, result)
        return result

    __radd__ = __add__
    __rmul__ = __mul__

    @property
    def symbol(self) -> str | None:
        """Return the currency symbol for this Money instance."""
        return self.currency.symbol

    @property
    def formatted_currency(self) -> str:
        """Return a formatted string with symbol and proper spacing.

        Uses babel's ``format_currency`` for locale-aware symbol
        positioning and number formatting.  The locale is read from
        ``format_options["locale"]`` (default ``"en_US"``).

        Pass a locale at construction to control formatting:

        .. code-block:: python

           m = Money("123456789.99", "EUR", format_options={"locale": "de_DE"})
           m.formatted_currency  # "123.456.789,99 €"

           m = Money("1500", "USD")
           m.formatted_currency  # "$ 1,500"

        Examples (default en_US locale):
            ``Money("100", "USD")`` -> ``"$ 100"``
            ``Money("19.99", "USD")`` -> ``"$ 19.99"``
            ``Money("1500", "EUR")`` -> ``"€ 1,500"``
            ``Money("1500", "SEK")`` -> ``"SEK 1,500"``
            ``Money("-5.50", "USD")`` -> ``"-$ 5.50"``
        """
        locale = DEFAULT_LOCALE
        if self.format_options is not None:
            locale_opt = self.format_options.get("locale")
            if isinstance(locale_opt, str):
                locale = locale_opt

        code = self.currency.code
        formatted = babel_format_currency(
            str(self.amount),
            code,
            locale=locale,
            currency_digits=False,
            decimal_quantization=False,
        )
        # Strip trailing .00 for whole numbers
        if "." in formatted:
            parts = formatted.rsplit(".", 1)
            if parts[1] == "0" * len(parts[1]):
                formatted = parts[0]
        # Insert a space between the symbol and the amount
        sym = babel_get_currency_symbol(code, locale=locale)
        if not sym:
            return formatted
        neg = formatted.startswith("-")
        rest = formatted[1:] if neg else formatted
        if sym == code:
            if rest.startswith(sym) and not rest[len(sym):].startswith(" "):
                formatted = ("-" if neg else "") + sym + " " + rest[len(sym):]
        elif rest.startswith(sym) and not rest[len(sym):].startswith(" "):
            formatted = ("-" if neg else "") + sym + " " + rest[len(sym):]
        return formatted

    @property
    def amount_in_words(self) -> str:
        """Return the amount spelled out in English words.

        Uses the currency's name and sub-unit name from the ISO 4217
        registry.  Examples:
            ``Money("100", "USD")`` -> ``"one hundred US Dollars"``
            ``Money("19.99", "USD")`` -> ``"nineteen US Dollars and ninety-nine cents"``
            ``Money("1", "EUR")`` -> ``"one Euro"``
        """
        currency_name = self.currency.name or self.currency.code

        irregular_plurals: dict[str, str] = {
            "yen": "yen",
            "Yen": "Yen",
            "rand": "rand",
            "Rand": "Rand",
            "baht": "baht",
            "Baht": "Baht",
            "ringgit": "ringgit",
            "Ringgit": "Ringgit",
        }
        last_word = currency_name.split()[-1] if currency_name else currency_name
        if last_word in irregular_plurals:
            major_singular = currency_name
            major_plural = currency_name.rsplit(last_word, 1)[0] + irregular_plurals[last_word]
        elif currency_name.endswith("s"):
            major_singular = currency_name
            major_plural = currency_name + "s"
        else:
            major_singular = currency_name
            major_plural = currency_name + "s"

        sub_unit = self.currency.sub_unit
        sub_name = ""
        sub_plural = ""
        if sub_unit and sub_unit > 1:
            sub_names: dict[int, tuple[str, str]] = {
                100: ("cent", "cents"),
                1000: ("mill", "mills"),
                10000: ("ten-thousandth", "ten-thousandths"),
            }
            sub_name, sub_plural = sub_names.get(
                sub_unit, (f"1/{sub_unit} part", f"1/{sub_unit} parts")
            )

        return convert_amount_to_words(
            self.amount,
            currency_name=major_singular,
            currency_plural=major_plural,
            sub_name=sub_name,
            sub_plural=sub_plural,
        )

    def __str__(self) -> str:
        decimal_quantization = True
        currency_digits = True
        locale = DEFAULT_LOCALE
        if self.format_options is not None:
            cast_mapping: Mapping[str, object] = self.format_options
            decimal_quantization = bool(cast_mapping.get("decimal_quantization", True))
            currency_digits = bool(cast_mapping.get("currency_digits", True))
            locale_opt = cast_mapping.get("locale")
            if isinstance(locale_opt, str):
                locale = locale_opt
        return format_money(
            self,
            decimal_quantization=decimal_quantization,
            currency_digits=currency_digits,
            locale=locale,
        )

    def quantize_to_currency(self) -> Money:
        """Quantize the amount to the currency's sub-unit precision.

        Falls back to the instance's decimal_places when the currency
        has sub_unit <= 1 (e.g. JPY with no fractional unit).
        """
        sub_unit = self.currency.sub_unit
        if sub_unit is None or sub_unit <= 1:
            quantizer = Decimal("1e" + str(-self.decimal_places))
            return self.__class__(
                amount=self.amount.quantize(quantizer),
                currency=self.currency,
                decimal_places=self.decimal_places,
            )
        decimals = 0
        sub = sub_unit
        while sub > 1:
            sub //= 10
            decimals += 1
        quantizer = Decimal("1e" + str(-decimals))
        return self.__class__(
            amount=self.amount.quantize(quantizer),
            currency=self.currency,
            decimal_places=self.decimal_places,
        )


__all__ = ["Currency", "Money"]


Currency = BaseCurrency
