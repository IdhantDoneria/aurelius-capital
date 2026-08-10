"""Currency codes & roles (AIDP M16).

ISO-4217-style validation and normalization. Every monetary value in M16 must carry a
currency; these helpers enforce that at the trust boundary so no ambiguous or silently
mismatched value slips through.
"""

from __future__ import annotations

import re

_CODE = re.compile(r"[A-Z]{3}")


class CurrencyMismatchError(ValueError):
    """Raised when two quantities that must share a currency do not."""


def normalize(code: str) -> str:
    if not isinstance(code, str):
        raise TypeError(f"currency code must be a string, got {type(code).__name__}")
    return code.strip().upper()


def is_valid_code(code) -> bool:
    try:
        return bool(_CODE.fullmatch(normalize(code)))
    except TypeError:
        return False


def validate_code(code) -> str:
    c = normalize(code)
    if not _CODE.fullmatch(c):
        raise ValueError(f"invalid ISO-style currency code {code!r}")
    return c


def same_currency(a, b) -> bool:
    return validate_code(a) == validate_code(b)


def require_same(a, b, *, ctx: str = "") -> str:
    """Assert two currencies match; return the (normalized) shared code."""
    ca, cb = validate_code(a), validate_code(b)
    if ca != cb:
        raise CurrencyMismatchError(f"currency mismatch{' in ' + ctx if ctx else ''}: {ca} != {cb}")
    return ca
