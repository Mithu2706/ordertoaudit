"""Rupee amounts in words, Indian numbering (lakh, crore), as printed on Indian invoices.

    rupees_in_words(Decimal("7875.00"))  -> "Rupees Seven Thousand Eight Hundred Seventy-Five Only"
    rupees_in_words(Decimal("187.50"))   -> "Rupees One Hundred Eighty-Seven and Fifty Paise Only"
"""
from decimal import ROUND_HALF_UP, Decimal

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _below_100(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return _TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else "")


def _below_1000(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = [f"{_ONES[hundreds]} Hundred"] if hundreds else []
    if rest:
        parts.append(_below_100(rest))
    return " ".join(parts)


def integer_in_words(n: int) -> str:
    if n == 0:
        return "Zero"
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1_000)
    if crore:
        parts.append(f"{integer_in_words(crore)} Crore")
    if lakh:
        parts.append(f"{_below_100(lakh)} Lakh")
    if thousand:
        parts.append(f"{_below_100(thousand)} Thousand")
    if n:
        parts.append(_below_1000(n))
    return " ".join(parts)


def rupees_in_words(amount: Decimal) -> str:
    amount = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rupees = int(amount)
    paise = int((amount - rupees) * 100)
    text = f"Rupees {integer_in_words(rupees)}"
    if paise:
        text += f" and {_below_100(paise)} Paise"
    return text + " Only"
