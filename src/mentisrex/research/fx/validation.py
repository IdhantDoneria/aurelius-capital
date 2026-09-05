"""Validation (AIDP M16).

M16 invariants on top of M15's. Reuses each per-currency book's M15 engine validation
(cash conservation, event-log ordering, settlement records, M11 double-entry), then adds
the FX faces: conversion conservation, non-positive rate rejection, and rate-inversion
consistency for every traded currency. No silent currency conversion is allowed.
"""

from __future__ import annotations

from mentisrex.research.post_trade.validation import ValidationResult
from mentisrex.research.post_trade.validation import validate_engine as _m15_validate


def validate_book(book, *, tol: float = 1e-6, inv_tol: float = 1e-6) -> ValidationResult:
    issues: list = []

    for ccy, eng in book.books.items():
        r = _m15_validate(eng)
        issues.extend(f"{ccy}:{i}" for i in r.issues)

    for fxc in book.conversions:
        if fxc.rate <= 0 or fxc.rate != fxc.rate:
            issues.append(f"nonpositive_rate:{fxc.conversion_id}")
        if abs(fxc.to_amount - fxc.from_amount * fxc.rate) > tol:
            issues.append(f"conversion_break:{fxc.conversion_id}")

    for ccy in book.currencies():
        if ccy == book.base_currency:
            continue
        r1 = book.provider.rate(ccy, book.base_currency)
        r2 = book.provider.rate(book.base_currency, ccy)
        if abs(r1 * r2 - 1.0) > inv_tol:
            issues.append(f"rate_inversion:{ccy}")

    return ValidationResult(ok=not issues, issues=issues)


def check_determinism(build_fn, *, n: int = 2) -> bool:
    """`build_fn()` builds and returns a fresh MultiCurrencyBook; its fingerprint must be
    identical across runs."""
    from mentisrex.research.fx.diagnostics import fingerprint

    return len({fingerprint(build_fn()) for _ in range(n)}) == 1
