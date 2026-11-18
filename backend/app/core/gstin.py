"""GSTIN format + checksum validation.

Layout (15 chars): 2-digit state code, 10-char PAN, entity number, 'Z', check character.
Checksum: base-36 weighted sum of the first 14 characters (weights alternate 1, 2;
each product contributes quotient + remainder of division by 36).
"""
import re

_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def gstin_check_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = _CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _CHARS[(36 - total % 36) % 36]


def gstin_error(gstin: str, state_code: str | None = None) -> str | None:
    """Return a human-readable problem, or None if the GSTIN is valid."""
    if not _PATTERN.match(gstin):
        return "GSTIN must be 15 characters: 2-digit state code, PAN, entity number, 'Z', check digit"
    if gstin[14] != gstin_check_char(gstin[:14]):
        return "GSTIN check digit is invalid"
    if state_code is not None and gstin[:2] != state_code:
        return f"GSTIN state code {gstin[:2]} does not match party state {state_code}"
    return None
