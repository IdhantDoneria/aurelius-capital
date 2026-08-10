"""Multi-currency reconciliation (AIDP M16).

Extends M12/M15 reconciliation across currencies. It reuses each per-currency book's own
M15 reconcile (cash vs M11, positions vs broker) tagged with its currency, then adds the
FX-specific faces: conversion conservation (to_amount == from_amount·rate), non-positive
/ wrong FX rate, and base-value consistency. Only diffs — never re-accounts.
"""

from __future__ import annotations

from datetime import date

from aurelius.research.fx.models import FXReconciliationReport
from aurelius.research.fx.valuation import valuation
from aurelius.research.post_trade.reconciliation import reconcile as _m15_reconcile


def reconcile(book, *, broker_accounts: dict | None = None, as_of: date | None = None,
              tol: float = 1e-6) -> FXReconciliationReport:
    diffs: list = []
    broker_accounts = broker_accounts or {}

    for ccy, eng in book.books.items():
        r = _m15_reconcile(eng, broker_account=broker_accounts.get(ccy), as_of=as_of)
        for d in r.differences:
            diffs.append({**d, "currency": ccy})

    for fxc in book.conversions:
        pair = f"{fxc.from_currency}/{fxc.to_currency}"
        if fxc.rate <= 0 or fxc.rate != fxc.rate:
            diffs.append({"category": "wrong_fx_rate", "currency": pair,
                          "internal": fxc.rate, "external": 0.0, "severity": "critical"})
        if abs(fxc.to_amount - fxc.from_amount * fxc.rate) > tol:
            diffs.append({"category": "fx_conversion_mismatch", "currency": pair,
                          "internal": fxc.to_amount, "external": fxc.from_amount * fxc.rate,
                          "severity": "critical"})

    val = valuation(book, as_of=as_of)
    recomputed = sum(cv.total_base for cv in val.by_currency.values())
    if abs(recomputed - val.total_base) > tol:
        diffs.append({"category": "valuation_mismatch", "currency": book.base_currency,
                      "internal": recomputed, "external": val.total_base, "severity": "critical"})

    cats: dict = {}
    for d in diffs:
        cats[d["category"]] = cats.get(d["category"], 0) + 1
    return FXReconciliationReport(ok=not diffs, differences=diffs, categories=cats,
                                  conversions_checked=len(book.conversions))
