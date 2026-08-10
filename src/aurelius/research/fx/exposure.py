"""FX exposure (AIDP M16).

Currency-by-currency exposure in base terms, split into cash / security / settlement
components, netted against any abstract hedges (`FXHedge`). The base currency itself
carries no FX exposure. Gross / net / long / short and the concentration (largest
currency share) roll up for limits and reporting.
"""

from __future__ import annotations

from datetime import date

from aurelius.research.fx.currency import validate_code
from aurelius.research.fx.models import FXExposure, FXExposureReport
from aurelius.research.fx.valuation import valuation


def fx_exposure(book, *, as_of: date | None = None, prices: dict | None = None) -> FXExposureReport:
    val = valuation(book, as_of=as_of, prices=prices)
    hedges_by: dict = {}
    for h in book.hedges:
        hedges_by[validate_code(h.currency)] = hedges_by.get(validate_code(h.currency), 0.0) + h.notional_base

    by: dict = {}
    gross = net = long = short = 0.0
    for ccy, cv in val.by_currency.items():
        if ccy == book.base_currency:
            continue                       # base carries no FX exposure
        eng = book.books[ccy]
        rate = cv.fx_rate_to_base
        cash_b = cv.cash_local * rate
        sec_b = cv.positions_local * rate
        settle_b = sum(abs(i.cash_amount) for i in eng.settlement.pending()) * rate
        hedge_b = hedges_by.get(ccy, 0.0)
        net_b = cv.total_base - hedge_b
        by[ccy] = FXExposure(
            currency=ccy, cash_exposure_base=cash_b, security_exposure_base=sec_b,
            settlement_exposure_base=settle_b, hedge_base=hedge_b,
            gross_base=abs(cv.total_base), net_base=net_b, unhedged_base=net_b)
        gross += abs(net_b)
        net += net_b
        long += net_b if net_b > 0 else 0.0
        short += -net_b if net_b < 0 else 0.0

    largest = max(by, key=lambda c: abs(by[c].net_base), default="")
    tv = val.total_base or 1.0
    return FXExposureReport(
        base_currency=book.base_currency, as_of=as_of, by_currency=by, gross=gross, net=net,
        long=long, short=short, largest_currency=largest,
        largest_share=abs(by[largest].net_base) / tv if largest else 0.0)
