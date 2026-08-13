"""Multi-currency reporting (AIDP M16).

Assembles the M16 report set from the engine state — pure reads over the reused books.
Most reports are built by their own modules; this module wires them together and adds
the cash-by-currency and composite portfolio reports.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.fx.exposure import fx_exposure
from mentisrex.research.fx.models import CashByCurrencyReport, MultiCurrencyPortfolioReport
from mentisrex.research.fx.multi_currency_cash import multi_currency_cash
from mentisrex.research.fx.pnl import fx_pnl
from mentisrex.research.fx.reconciliation import reconcile
from mentisrex.research.fx.risk import fx_risk_report
from mentisrex.research.fx.settlement_fx import settlement_by_currency
from mentisrex.research.fx.valuation import valuation

# re-exports so the whole M16 report set lives behind one import
exposure_report = fx_exposure
fx_pnl_report = fx_pnl
fx_reconciliation_report = reconcile
settlement_currency_report = settlement_by_currency


def cash_by_currency_report(book, *, as_of: date | None = None) -> CashByCurrencyReport:
    mc = multi_currency_cash(book, as_of=as_of)
    return CashByCurrencyReport(base_currency=book.base_currency, as_of=as_of,
                                balances=mc.balances, total_base=mc.total_base_economic)


def multi_currency_portfolio_report(book, *, as_of: date | None = None, prices: dict | None = None,
                                    snap0: dict | None = None, snap1: dict | None = None
                                    ) -> MultiCurrencyPortfolioReport:
    return MultiCurrencyPortfolioReport(
        base_currency=book.base_currency, as_of=as_of,
        value=valuation(book, as_of=as_of, prices=prices),
        cash=cash_by_currency_report(book, as_of=as_of),
        exposure=fx_exposure(book, as_of=as_of),
        reconciliation=reconcile(book, as_of=as_of),
        pnl=(fx_pnl(book, snap0, snap1) if snap0 is not None and snap1 is not None else None),
        n_currencies=len(book.currencies()), n_conversions=len(book.conversions))


__all__ = ["cash_by_currency_report", "exposure_report", "fx_pnl_report",
           "fx_reconciliation_report", "fx_risk_report", "multi_currency_portfolio_report",
           "settlement_currency_report"]
