"""Fundamental analytics engine (AIDP M21).

Computes FinanceToolkit-style ratios from CanonicalObservation inputs. This layer sits ABOVE
the data pipeline (M19 normalization) and BELOW research/screening. It does NOT replace:
    - M11 multi-period accounting
    - M13 risk engine
    - M18 valuation engine

All ratio computations are pure functions: given a dict of field → value, return a ratio.
FundamentalObservation is the typed output — a named ratio with provenance.

Ratio taxonomy:
    Profitability: ROE, ROA, ROIC, gross_margin, operating_margin, net_margin, ebitda_margin
    Valuation:     PE, PB, PS, EV/EBITDA (requires price from market data)
    Efficiency:    asset_turnover, inventory_turnover, receivables_turnover
    Leverage:      debt_to_equity, debt_to_assets, interest_coverage, net_debt_to_ebitda
    Liquidity:     current_ratio, quick_ratio, cash_ratio
    Growth:        revenue_growth, earnings_growth (requires prior-period values)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class FundamentalObservation:
    """A named fundamental ratio with full provenance.

    observation_date: when the underlying data was knowable (PIT-safe).
    effective_date:   the accounting period end the ratio corresponds to.
    security_id:      canonical internal id.
    ratio_name:       e.g. "gross_margin", "roe", "pe_ratio".
    value:            the computed ratio (NaN-like sentinel: None means not computable).
    inputs:           the field values used to compute this ratio (for audit/debug).
    """

    security_id: str
    ratio_name: str
    value: float | None
    observation_date: date
    effective_date: date
    source: str = "fundamentals"
    inputs: dict = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return self.value is not None and not (self.value != self.value)  # NaN guard


def _safe_div(numerator, denominator) -> float | None:
    try:
        n, d = float(numerator), float(denominator)
    except (TypeError, ValueError):
        return None
    if d == 0.0:
        return None
    return n / d


class FundamentalRatioEngine:
    """Computes FundamentalObservation ratios from a dict of field values.

    Usage:
        engine = FundamentalRatioEngine()
        ratios = engine.compute(security_id, fields, observation_date, effective_date)
    """

    def compute(
        self,
        security_id: str,
        fields: dict,
        observation_date: date,
        effective_date: date,
        *,
        source: str = "fundamentals",
        price: float | None = None,
    ) -> list[FundamentalObservation]:
        """Compute all available ratios from the provided field dict.

        fields: {field_name: value} — e.g. {"revenue": 1e9, "net_income": 1e8, ...}
        price:  current market price (enables valuation multiples like P/E, P/B)
        """
        results = []

        def obs(name: str, value, inp: dict) -> None:
            results.append(
                FundamentalObservation(
                    security_id=security_id,
                    ratio_name=name,
                    value=value,
                    observation_date=observation_date,
                    effective_date=effective_date,
                    source=source,
                    inputs=inp,
                )
            )

        f = fields

        # ── Profitability ratios ──────────────────────────────────────────────
        rev = f.get("revenue")
        gp = f.get("gross_profit")
        oi = f.get("operating_income")
        ni = f.get("net_income")
        ebitda = f.get("ebitda")
        assets = f.get("total_assets")
        equity = f.get("stockholders_equity")
        interest = f.get("interest_expense")

        obs("gross_margin", _safe_div(gp, rev), {"gross_profit": gp, "revenue": rev})
        obs("operating_margin", _safe_div(oi, rev), {"operating_income": oi, "revenue": rev})
        obs("net_margin", _safe_div(ni, rev), {"net_income": ni, "revenue": rev})
        obs("ebitda_margin", _safe_div(ebitda, rev), {"ebitda": ebitda, "revenue": rev})
        obs("roe", _safe_div(ni, equity), {"net_income": ni, "stockholders_equity": equity})
        obs("roa", _safe_div(ni, assets), {"net_income": ni, "total_assets": assets})

        # ── Leverage ratios ────────────────────────────────────────────────────
        ltd = f.get("long_term_debt")
        cash = f.get("cash")
        obs(
            "debt_to_equity",
            _safe_div(ltd, equity),
            {"long_term_debt": ltd, "stockholders_equity": equity},
        )
        obs(
            "debt_to_assets",
            _safe_div(ltd, assets),
            {"long_term_debt": ltd, "total_assets": assets},
        )
        obs(
            "interest_coverage",
            _safe_div(oi, interest),
            {"operating_income": oi, "interest_expense": interest},
        )
        net_debt = (
            (float(ltd or 0) - float(cash or 0)) if (ltd is not None or cash is not None) else None
        )
        obs(
            "net_debt_to_ebitda",
            _safe_div(net_debt, ebitda),
            {"long_term_debt": ltd, "cash": cash, "ebitda": ebitda},
        )

        # ── Liquidity ratios ──────────────────────────────────────────────────
        ca = f.get("current_assets")
        cl = f.get("current_liabilities")
        obs("current_ratio", _safe_div(ca, cl), {"current_assets": ca, "current_liabilities": cl})
        # quick ratio: (current_assets - inventory) / current_liabilities
        # inventory not always available — approximate with current_assets
        obs("cash_ratio", _safe_div(cash, cl), {"cash": cash, "current_liabilities": cl})

        # ── Efficiency ratios ─────────────────────────────────────────────────
        obs("asset_turnover", _safe_div(rev, assets), {"revenue": rev, "total_assets": assets})

        # ── Valuation multiples (require market price) ────────────────────────
        if price is not None:
            shares = f.get("shares_outstanding")
            eps = f.get("eps") or f.get("eps_diluted")
            book_per_share = _safe_div(equity, shares)
            rev_per_share = _safe_div(rev, shares)

            obs("pe_ratio", _safe_div(price, eps), {"price": price, "eps": eps})
            obs(
                "pb_ratio",
                _safe_div(price, book_per_share),
                {"price": price, "book_per_share": book_per_share},
            )
            obs(
                "ps_ratio",
                _safe_div(price, rev_per_share),
                {"price": price, "revenue_per_share": rev_per_share},
            )

        # ── Cash flow ratios ──────────────────────────────────────────────────
        cfo = f.get("cash_flow_operations")
        capex = f.get("capex")
        fcf = f.get("free_cash_flow") or (
            (float(cfo) - float(capex)) if (cfo is not None and capex is not None) else None
        )
        obs("fcf_margin", _safe_div(fcf, rev), {"free_cash_flow": fcf, "revenue": rev})
        obs("fcf_to_net_income", _safe_div(fcf, ni), {"free_cash_flow": fcf, "net_income": ni})

        return [r for r in results if r.valid]

    def compute_growth(
        self,
        security_id: str,
        current: dict,
        prior: dict,
        observation_date: date,
        effective_date: date,
        *,
        source: str = "fundamentals",
    ) -> list[FundamentalObservation]:
        """Compute YoY growth rates given current and prior period field dicts."""
        results = []

        def obs(name: str, value, inp: dict) -> None:
            results.append(
                FundamentalObservation(
                    security_id=security_id,
                    ratio_name=name,
                    value=value,
                    observation_date=observation_date,
                    effective_date=effective_date,
                    source=source,
                    inputs=inp,
                )
            )

        for field_name, ratio_name in (
            ("revenue", "revenue_growth"),
            ("net_income", "earnings_growth"),
            ("gross_profit", "gross_profit_growth"),
            ("ebitda", "ebitda_growth"),
            ("cash_flow_operations", "cfo_growth"),
        ):
            curr_val = current.get(field_name)
            prev_val = prior.get(field_name)
            if curr_val is not None and prev_val is not None and float(prev_val) != 0.0:
                growth = (float(curr_val) - float(prev_val)) / abs(float(prev_val))
                obs(
                    ratio_name,
                    growth,
                    {f"current_{field_name}": curr_val, f"prior_{field_name}": prev_val},
                )

        return [r for r in results if r.valid]
