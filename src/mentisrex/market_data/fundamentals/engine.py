"""Point-in-time fundamentals engine (AIDP M3).

Composes the three PIT layers:
  SecurityMaster (M2)  → the ticker a security traded under on a date
  PitPriceStore  (M1)  → the price known as of that date
  FundamentalsStore         → the filed fundamental known as of that date

Everything routes through fact_as_of, so no future filing can influence an
earlier query. Feature ratios are thin, deterministic compositions of the
`*_as_of` primitives — inputs for factor models, not optimized factors.
"""

from __future__ import annotations

from datetime import date

from mentisrex.market_data.fundamentals.store import FundamentalsStore

# Friendly name → ordered us-gaap concept candidates (first that resolves wins).
CONCEPTS: dict[str, list[str]] = {
    "shares_basic": ["WeightedAverageNumberOfSharesOutstandingBasic"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "shares_outstanding": ["CommonStockSharesOutstanding", "EntityCommonStockSharesOutstanding"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "dep_amort": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
}


class FundamentalsEngine:
    def __init__(self, store: FundamentalsStore, *, price_store=None, security_master=None) -> None:
        self._store = store
        self._prices = price_store
        self._sm = security_master

    # ── raw concept access ──────────────────────────────────────────────────────

    def fundamental_as_of(self, cik: str, name: str, as_of: date, *,
                          knowledge_date: date | None = None,
                          fiscal_period: str | None = None) -> float | None:
        """Resolve a friendly `name` to its concept candidates and return the PIT
        value (None if none reported as of the knowledge date)."""
        for concept in CONCEPTS.get(name, [name]):
            row = self._store.fact_as_of(cik, concept, as_of,
                                         knowledge_date=knowledge_date, fiscal_period=fiscal_period)
            if row is not None:
                return row["value"]
        return None

    def shares_as_of(self, cik: str, as_of: date, *, knowledge_date: date | None = None,
                     kind: str = "shares_outstanding") -> float | None:
        """Shares as of a date. kind ∈ shares_outstanding|shares_basic|shares_diluted."""
        return self.fundamental_as_of(cik, kind, as_of, knowledge_date=knowledge_date)

    def book_value_as_of(self, cik: str, as_of: date, *, knowledge_date: date | None = None) -> float | None:
        return self.fundamental_as_of(cik, "equity", as_of, knowledge_date=knowledge_date)

    # ── price-integrated (M1 + 2) ──────────────────────────────────────────

    def _pit_ticker(self, security_id: str | None, ticker: str | None, as_of: date) -> str | None:
        if ticker is not None:
            return ticker
        if security_id is not None and self._sm is not None:
            return self._sm.historical_identifier(security_id, as_of)
        return None

    def market_cap_as_of(self, cik: str, as_of: date, *, ticker: str | None = None,
                         security_id: str | None = None, knowledge_date: date | None = None) -> float | None:
        """PIT market cap = shares known as-of × price known as-of. Ticker is
        resolved point-in-time from SecurityMaster when only a security_id is given."""
        if self._prices is None:
            raise ValueError("market_cap_as_of needs a price_store")
        shares = self.shares_as_of(cik, as_of, knowledge_date=knowledge_date)
        tkr = self._pit_ticker(security_id, ticker, as_of)
        if shares is None or tkr is None:
            return None
        price = self._prices.close_as_of(tkr, as_of, knowledge_date=knowledge_date)
        if price is None:
            return None
        return shares * float(price)

    def enterprise_value_as_of(self, cik: str, as_of: date, *, ticker: str | None = None,
                               security_id: str | None = None, knowledge_date: date | None = None) -> float | None:
        """EV = market cap + total debt − cash & equivalents (all PIT)."""
        mc = self.market_cap_as_of(cik, as_of, ticker=ticker, security_id=security_id,
                                   knowledge_date=knowledge_date)
        if mc is None:
            return None
        debt = self.fundamental_as_of(cik, "debt", as_of, knowledge_date=knowledge_date) or 0.0
        cash = self.fundamental_as_of(cik, "cash", as_of, knowledge_date=knowledge_date) or 0.0
        return mc + debt - cash

    # ── factor inputs (thin, PIT) ───────────────────────────────────────────────

    def factor_inputs_as_of(self, cik: str, as_of: date, *, ticker: str | None = None,
                            security_id: str | None = None, knowledge_date: date | None = None) -> dict[str, float | None]:
        """Reusable point-in-time inputs for value/quality/profitability/investment
        factor models. Ratios only — never look-ahead. None where an input is
        unavailable as of the knowledge date."""
        k = knowledge_date
        f = lambda n: self.fundamental_as_of(cik, n, as_of, knowledge_date=k)  # noqa: E731
        mc = self.market_cap_as_of(cik, as_of, ticker=ticker, security_id=security_id, knowledge_date=k)
        ev = self.enterprise_value_as_of(cik, as_of, ticker=ticker, security_id=security_id, knowledge_date=k)
        equity, assets, liabilities = f("equity"), f("assets"), f("liabilities")
        cur_a, cur_l = f("current_assets"), f("current_liabilities")
        revenue, gross, op_inc = f("revenue"), f("gross_profit"), f("operating_income")
        ni, ocf, debt = f("net_income"), f("operating_cash_flow"), f("debt")
        ebitda = (op_inc + (f("dep_amort") or 0.0)) if op_inc is not None else None

        def div(a, b):
            return a / b if (a is not None and b not in (None, 0)) else None

        return {
            "book_to_market": div(equity, mc),
            "price_to_book": div(mc, equity),
            "price_to_sales": div(mc, revenue),
            "earnings_yield": div(ni, mc),
            "cash_flow_yield": div(ocf, mc),
            "ev_ebitda": div(ev, ebitda),
            "debt_to_equity": div(debt, equity),
            "current_ratio": div(cur_a, cur_l),
            "roe": div(ni, equity),
            "roa": div(ni, assets),
            "gross_profitability": div(gross, assets),
            "operating_margin": div(op_inc, revenue),
            "accruals": div((ni - ocf) if (ni is not None and ocf is not None) else None, assets),
            # asset_growth / investment need a prior-period asset value:
            "asset_growth": self._asset_growth(cik, as_of, k),
            "market_cap": mc,
            "enterprise_value": ev,
        }

    def _asset_growth(self, cik: str, as_of: date, knowledge_date: date | None) -> float | None:
        """YoY asset growth (investment factor input) from the two most recent
        annual asset values known as of the knowledge date."""
        series = self._store.series_as_of(cik, "Assets", knowledge_date or as_of)
        series = [s for s in series if s["period_end"] <= as_of]
        if len(series) < 2:
            return None
        latest, prior = series[-1]["value"], series[-2]["value"]
        return (latest - prior) / prior if prior else None
