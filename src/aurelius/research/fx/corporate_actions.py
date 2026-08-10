"""Multi-currency corporate actions (AIDP M16).

Thin wrapper over M15 corporate actions. A corporate action on a security is applied
inside that security's trading-currency book, so its cash impact (dividend, cash merger
terms, delisting proceeds) lands in the correct currency automatically — M15 accounting
is reused verbatim. Optionally the received cash is converted into another currency,
preserving source currency, received currency, and the FX conversion used.
"""

from __future__ import annotations

from datetime import date

from aurelius.research.fx.currency import validate_code
from aurelius.research.post_trade import corporate_actions as _m15_ca


def apply(book, action, *, when: date | None = None, receive_currency: str | None = None):
    """Apply `action` in the security's trading-currency book. If `receive_currency` is
    given and differs, convert the resulting cash impact into it (cross-currency CA)."""
    ccy = book.security_currency.get(action.security_id, book.base_currency)
    eng = book.book(ccy)
    ev = _m15_ca.apply(eng, action, when=when)

    if receive_currency and validate_code(receive_currency) != ccy and ev.cash_impact:
        book.convert(amount=ev.cash_impact, from_currency=ccy, to_currency=receive_currency,
                     when=when, reason="corporate_action_fx")
    return ev
