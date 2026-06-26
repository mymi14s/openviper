"""Convert monetary amounts to English words.

Supports amounts up to trillions with decimal cents. Used by
``Money.amount_in_words`` for check-printing and invoice displays.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

ONES: tuple[str, ...] = (
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
)

TENS: tuple[str, ...] = (
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
)

HUNDREDS: tuple[str, ...] = (
    "",
    "one hundred",
    "two hundred",
    "three hundred",
    "four hundred",
    "five hundred",
    "six hundred",
    "seven hundred",
    "eight hundred",
    "nine hundred",
)

SCALES: tuple[str, ...] = (
    "",
    "thousand",
    "million",
    "billion",
    "trillion",
    "quadrillion",
)

MAX_VALUE = Decimal(10) ** 18


def three_digits_to_words(n: int) -> str:
    """Convert a 3-digit number (0-999) to words."""
    if n == 0:
        return "zero"
    parts: list[str] = []
    hundreds, remainder = divmod(n, 100)
    if hundreds:
        parts.append(HUNDREDS[hundreds])
    if remainder >= 20:
        tens_digit, ones_digit = divmod(remainder, 10)
        if ones_digit:
            parts.append(f"{TENS[tens_digit]}-{ONES[ones_digit]}")
        else:
            parts.append(TENS[tens_digit])
    elif remainder > 0:
        parts.append(ONES[remainder])
    return " ".join(parts)


def integer_to_words(n: int) -> str:
    """Convert a non-negative integer to words."""
    if n == 0:
        return "zero"
    groups: list[int] = []
    remaining = n
    while remaining > 0:
        remaining, group = divmod(remaining, 1000)
        groups.append(group)
    if len(groups) > len(SCALES):
        raise ValueError(f"Amount exceeds supported scale ({len(SCALES)} groups).")
    words_parts: list[str] = []
    for scale_index, group in enumerate(groups):
        if group == 0:
            continue
        group_words = three_digits_to_words(group)
        if scale_index > 0:
            group_words = f"{group_words} {SCALES[scale_index]}"
        words_parts.append(group_words)
    words_parts.reverse()
    return " ".join(words_parts)


def convert_amount_to_words(
    amount: Decimal | str | int | float,
    *,
    currency_name: str = "dollar",
    currency_plural: str = "dollars",
    sub_name: str = "cent",
    sub_plural: str = "cents",
) -> str:
    """Convert a monetary amount to English words.

    Args:
        amount: The monetary value to convert.
        currency_name: Singular name of the major currency unit.
        currency_plural: Plural name of the major currency unit.
        sub_name: Singular name of the minor currency unit.
        sub_plural: Plural name of the minor currency unit.

    Returns:
        The amount spelled out in words, e.g.
        ``"one hundred dollars and fifty cents"``.

    Raises:
        ValueError: If the amount exceeds 10**18, is negative,
            or sub_name is empty but the amount has a fractional part.
    """
    dec = Decimal(str(amount))
    if dec < 0:
        raise ValueError("Negative amounts are not supported.")
    if dec >= MAX_VALUE:
        raise ValueError("Amount exceeds maximum supported value (10^18).")

    whole = int(dec // 1)
    fractional = dec % 1
    cents = int((fractional * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    if cents >= 100:
        whole += cents // 100
        cents = cents % 100

    parts: list[str] = []

    if whole == 0:
        parts.append("zero")
    else:
        parts.append(integer_to_words(whole))
    parts.append(currency_name if whole == 1 else currency_plural)

    if cents > 0:
        if not sub_name:
            raise ValueError(
                "Amount has a fractional part but sub_name is empty. "
                "Provide sub_name/sub_plural for this currency."
            )
        parts.append("and")
        parts.append(integer_to_words(cents))
        parts.append(sub_name if cents == 1 else sub_plural)

    return " ".join(parts)


__all__ = ["convert_amount_to_words", "integer_to_words", "three_digits_to_words"]
