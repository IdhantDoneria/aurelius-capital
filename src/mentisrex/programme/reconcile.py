"""Target versus actual -- the 08:30 reconciliation step (spec Table 27).

Table 27's first row of the daily sequence is: reconcile yesterday's fills
against target, compute realised slippage, and treat a per-name drift beyond
`config.execution.reconcile_drift_bps` (25 bp of NAV) as a reason to
investigate *before* trading, not after. This module is that check.

It also carries the responsibility spec section 13.3 calls out by name:
"Measure costs; do not infer them." `realised_cost_bps` is computed from
actual fills against the reference (backtest-marking) price -- never assumed
from the cost model. `modelled_cost_bps` sits alongside it purely as the
figure the cost model *assumes* (`config.costs.one_way_bps`), so a caller can
see the gap directly. That gap is exactly the failure mode section 13.3
describes: realised costs drifting to 12-15 bps while the model still
assumes 5, quietly eating the return while it gets attributed to signal
decay.

Pure function, and it never raises: a zero/negative NAV or a symbol with no
price cannot be reconciled, so those cases are logged and folded into the
report (a NaN `total_drift_bps`, or the unpriceable symbol simply omitted
from the per-name drift sum) rather than raising -- the 08:30 run must get an
answer, not an exception.

Numeric core is float64 pandas/numpy, per house convention (see
`mentisrex/programme/config.py`'s module docstring). This is a monitoring
report, not the ledger, so nothing here touches `Decimal`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from mentisrex.core.logging import get_logger
from mentisrex.programme.config import ProgrammeConfig

logger = get_logger(__name__)


@dataclass(frozen=True)
class Drift:
    """One name's live position versus its target, in bps of NAV."""

    symbol: str
    target_weight: float
    actual_weight: float
    drift_bps: float


@dataclass(frozen=True)
class ReconciliationReport:
    """Output of `reconcile`. `drifts` holds only names that breached
    `config.execution.reconcile_drift_bps`; `total_drift_bps` sums the
    absolute drift over every name that could be priced, breaching or not."""

    as_of: pd.Timestamp
    drifts: tuple[Drift, ...]
    realised_cost_bps: float | None
    modelled_cost_bps: float | None
    n_positions: int
    total_drift_bps: float

    @property
    def ok(self) -> bool:
        """True iff no name breached the drift threshold *and* drift was
        actually computable.

        CONTRACT-NOTE: the contract text for this property says only "True
        when no name breaches the drift threshold". This adds one guard: a
        zero/negative NAV makes every weight undefined, not zero, and
        `reconcile` marks that with `total_drift_bps = NaN`. Treating NaN as
        "ok" would let a reconciliation that never actually ran read as a
        clean one, which is precisely the silent pass the rest of this
        module is built to avoid.
        """
        return len(self.drifts) == 0 and not math.isnan(self.total_drift_bps)


def _realised_cost_bps(
    fills: pd.DataFrame | None, reference_prices: pd.Series | None
) -> float | None:
    """Notional-weighted mean fill slippage in bps (spec Table 27's 08:30
    row; section 13.3: "measure costs; do not infer them").

    Expects `fills` with `symbol`, `quantity` and `fill_price` columns -- the
    same fill-record shape used elsewhere in this repo (see
    `mentisrex.backtesting.events.types.Fill`). A fill whose symbol has no
    reference price, or whose reference price is zero/NaN, cannot be
    measured and is dropped (logged), never assumed zero-cost.
    """
    if fills is None or reference_prices is None or fills.empty:
        return None
    required = {"symbol", "quantity", "fill_price"}
    if not required.issubset(fills.columns):
        logger.warning(
            "programme_reconcile_fills_missing_columns",
            columns=list(fills.columns),
            required=sorted(required),
        )
        return None

    reference = reference_prices.reindex(fills["symbol"]).to_numpy(dtype=float)
    fill_price = fills["fill_price"].to_numpy(dtype=float)
    quantity = fills["quantity"].to_numpy(dtype=float)

    valid = np.isfinite(reference) & (reference != 0) & np.isfinite(fill_price)
    if not valid.any():
        logger.warning("programme_reconcile_no_priceable_fills", n_fills=len(fills))
        return None

    notional = np.abs(quantity[valid] * fill_price[valid])
    total_notional = notional.sum()
    if total_notional <= 0:
        logger.warning("programme_reconcile_zero_fill_notional")
        return None

    slippage_bps = np.abs(fill_price[valid] - reference[valid]) / reference[valid] * 10_000
    return float(np.average(slippage_bps, weights=notional))


def reconcile(
    target: pd.Series,
    positions: Mapping[str, float],
    prices: pd.Series,
    nav: float,
    config: ProgrammeConfig,
    as_of: pd.Timestamp,
    fills: pd.DataFrame | None = None,
    reference_prices: pd.Series | None = None,
) -> ReconciliationReport:
    """Reconcile yesterday's actual book against the target (spec Table 27,
    08:30 row).

    `actual_weight = positions[symbol] * prices[symbol] / nav`; drift is
    `(actual_weight - target_weight) * 10_000` bps of NAV. A name whose
    absolute drift exceeds `config.execution.reconcile_drift_bps` (25 bp)
    appears in `report.drifts`; `total_drift_bps` sums absolute drift over
    every priceable name, regardless of breach.

    `fills` / `reference_prices` are optional: when both are supplied,
    `realised_cost_bps` is measured from them. `modelled_cost_bps` is always
    `config.costs.one_way_bps` -- the model's assumption, for comparison,
    never a computed or inferred figure.

    Never raises. A NaN or non-positive `nav` makes every weight undefined;
    that case is logged and returned with `total_drift_bps = NaN` rather
    than fabricating a zero-drift pass. A symbol with a missing/NaN price is
    skipped from the per-name drift calculation (logged), not treated as a
    100%-drifted position.
    """
    prices = prices if prices is not None else pd.Series(dtype=float)
    threshold = config.execution.reconcile_drift_bps
    realised_cost = _realised_cost_bps(fills, reference_prices)
    modelled_cost = config.costs.one_way_bps

    if nav is None or not math.isfinite(nav) or nav <= 0:
        logger.warning("programme_reconcile_invalid_nav", nav=nav, as_of=str(as_of))
        return ReconciliationReport(
            as_of=as_of,
            drifts=(),
            realised_cost_bps=realised_cost,
            modelled_cost_bps=modelled_cost,
            n_positions=len(positions),
            total_drift_bps=float("nan"),
        )

    symbols = sorted(set(target.index) | set(positions.keys()))
    drifts: list[Drift] = []
    total_drift_bps = 0.0
    for symbol in symbols:
        target_weight = float(target.get(symbol, 0.0))
        shares = float(positions.get(symbol, 0.0))
        price = prices.get(symbol)
        if pd.isna(price):
            logger.warning("programme_reconcile_missing_price", symbol=symbol, as_of=str(as_of))
            continue
        actual_weight = shares * float(price) / nav
        drift_bps = (actual_weight - target_weight) * 10_000
        total_drift_bps += abs(drift_bps)
        if abs(drift_bps) > threshold:
            drifts.append(
                Drift(
                    symbol=symbol,
                    target_weight=target_weight,
                    actual_weight=actual_weight,
                    drift_bps=drift_bps,
                )
            )

    report = ReconciliationReport(
        as_of=as_of,
        drifts=tuple(drifts),
        realised_cost_bps=realised_cost,
        modelled_cost_bps=modelled_cost,
        n_positions=len(positions),
        total_drift_bps=total_drift_bps,
    )
    logger.info(
        "programme_reconcile",
        as_of=str(as_of),
        n_positions=report.n_positions,
        n_drifted=len(report.drifts),
        total_drift_bps=report.total_drift_bps,
        realised_cost_bps=report.realised_cost_bps,
        modelled_cost_bps=report.modelled_cost_bps,
        ok=report.ok,
    )
    return report
