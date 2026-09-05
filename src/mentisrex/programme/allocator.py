"""Ten sleeves to one book: the gross cap, position caps, and financing (spec §2, §4.2).

This module is where the two accounting defects Version 3 of the spec is
proudest of fixing are actually fixed (spec §2, "What changed from Version 2"):

1. **The gross cap is charged against the combined book, never the sum of
   standalone sleeve grosses** (spec §2.1). Six cross-sectional books averaged
   together net against one another: if the momentum sleeve is long a name 40
   bp and the reversal sleeve is short it 35 bp, the combined book holds 5 bp,
   and 5 bp is what a broker finances and what actually gets traded. `combine`
   builds `RAW = CORE + SATELLITE` as one weight vector FIRST, and only then
   computes `f = min(1, cap / RAW.abs().sum(axis=1))`. Summing per-sleeve
   grosses and capping that sum was the Version 2 bug; it made the
   market-neutral layer look expensive in notional terms and squeezed the
   optimal satellite multiplier down to a fraction of its correct value.

2. **Two position caps, not one** (spec §2.2). `max_position` (20% of NAV)
   applies to every single non-benchmark name; `max_position_benchmark` (300%
   of NAV) applies only to the benchmark column. A single-name cap exists to
   control idiosyncratic risk — the chance that one company's accounting
   fraud takes a fifth of the book with it. An S&P 500 ETF carries no such
   risk: its concentration is market risk, already governed by the gross cap
   and the drawdown budget, not by a name limit. Applying the 20% name cap to
   the index column pinned the entire directional layer at 20% of NAV for
   every k_core from 3 to 6 in an earlier version — a flat 3.2%-a-year line
   that is the signature of a binding constraint nobody intended.

Numeric core is `float64` numpy/pandas throughout, consistent with the rest of
`programme/`; conversion to `Decimal` happens only at the broker boundary
(`execution.py`), not here.

No look-ahead: every function here is a pure, same-day transform of its
inputs. The only place any of the pipeline shifts time is `sleeves.py`
(holding-period drift, lag in `sleeve_returns`) and `book_returns` below,
which applies `execution.signal_to_trade_lag` to `target_weights` and to the
two cost series so a cost lands on the day the trade that caused it actually
happens (spec §2.4).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mentisrex.core.logging import get_logger
from mentisrex.programme.config import (
    CORE_SLEEVES,
    SATELLITE_SLEEVES,
    CostConfig,
    FinancingConfig,
    ProgrammeConfig,
)
from mentisrex.programme.sleeves import Sleeve, volatility_scalar

logger = get_logger(__name__)


@dataclass(frozen=True)
class Book:
    """The combined ten-sleeve book, before and after the gross and position caps.

    All weight frames are date x `panel.columns` (universe tickers ascending,
    benchmark last), fraction of NAV. All series are date-indexed.
    """

    raw_weights: pd.DataFrame  # CORE + SATELLITE, before any cap
    target_weights: pd.DataFrame  # after gross cap and position caps
    gross: pd.Series  # target_weights.abs().sum(axis=1)
    net: pd.Series  # target_weights.sum(axis=1)
    long_exposure: pd.Series  # sum of positive target_weights
    short_exposure: pd.Series  # sum of |negative target_weights|
    cap_scalar: pd.Series  # f(t), spec §4.2
    turnover: pd.Series  # one-way notional traded in target_weights
    core_weights: pd.DataFrame  # mean(S1..S4) * k_core, pre-cap
    satellite_weights: pd.DataFrame  # mean(vol-scaled S5..S10) * k_satellite, pre-cap
    satellite_scalars: pd.DataFrame  # date x satellite sleeve name, the vol-target scalar


def combine(
    sleeves: dict[str, Sleeve],
    panel: object,
    config: ProgrammeConfig,
    effective_cap: float | pd.Series | None = None,
    sleeve_multipliers: dict[str, float] | None = None,
) -> Book:
    """Combine ten sleeves into one book (spec §4.2, exactly):

        CORE      = mean(S1..S4 weight frames) * k_core
        SATELLITE = mean(vol-scaled S5..S10 weight frames) * k_satellite
        RAW       = CORE + SATELLITE
        f         = min(1, cap / RAW.abs().sum(axis=1))
        TARGET    = clip(RAW * f, per-name limits)

    Directional sleeves (S1-S4) are NOT vol-targeted here: each already sizes
    its own exposure inversely to volatility internally (S2 explicitly; S1/S3/
    S4 implicitly through their trigger design). Targeting them again would
    double-count that sizing and de-lever the book precisely in the recovery
    where the return is (spec §4.2).

    Each satellite sleeve's weights are first multiplied by
    `sleeves.volatility_scalar(sleeve.gross_returns, satellite_vol_target,
    satellite_vol_window, floor, cap)` before being averaged.

    `panel` is a `PricePanel` (data.py); only `.columns` and `.benchmark` are
    used here, so a lightweight stand-in with those two attributes also works
    (matching the duck-typing convention already used in sleeves.py, since
    data.py does not exist in this worktree yet).

    `effective_cap` overrides `config.allocator.gross_cap` when given: a float
    for a single fixed cap, or a `pd.Series` aligned to the sleeve index so the
    risk engine (DERISK halving) and the deployment ramp (spec Table 7) can
    vary the cap by date. `sleeve_multipliers` scales individual sleeves'
    contribution to CORE/SATELLITE before averaging (sleeve-health de-risking,
    spec Table 15) — a sleeve absent from the mapping is left at 1.0.

    Per-name caps: `max_position` (20%, spec §2.2) applies to every column
    except the benchmark; `max_position_benchmark` (300%) applies only to the
    benchmark column, since an index ETF's concentration risk is market risk
    already governed by the gross cap, not idiosyncratic risk. Applying the
    single-name cap to the benchmark pinned the whole directional layer at 20%
    of NAV in an earlier version — see the module docstring.

    Position caps are applied AFTER the gross-cap scaledown, per spec §4.2's
    `TARGET = clip(RAW * f, ...)`. `gross`/`net`/`long_exposure`/
    `short_exposure` are computed from the post-clip `target_weights`, so a
    name that hits its position cap can leave gross a hair under the nominal
    cap; `test_gross_cap_never_breached` only requires gross to never exceed
    the cap, which clipping downward can never violate.
    """
    allocator_cfg = config.allocator
    multipliers = sleeve_multipliers or {}
    columns = panel.columns
    benchmark = panel.benchmark

    core_frames = [
        sleeves[name].weights.reindex(columns=columns, fill_value=0.0) * multipliers.get(name, 1.0)
        for name in CORE_SLEEVES
    ]
    core_weights = sum(core_frames) / len(core_frames) * allocator_cfg.k_core

    satellite_scalars = pd.DataFrame(
        {
            name: volatility_scalar(
                sleeves[name].gross_returns,
                allocator_cfg.satellite_vol_target,
                allocator_cfg.satellite_vol_window,
                allocator_cfg.satellite_scalar_floor,
                allocator_cfg.satellite_scalar_cap,
            )
            for name in SATELLITE_SLEEVES
        }
    )

    satellite_frames = [
        sleeves[name]
        .weights.reindex(columns=columns, fill_value=0.0)
        .mul(satellite_scalars[name], axis=0)
        * multipliers.get(name, 1.0)
        for name in SATELLITE_SLEEVES
    ]
    satellite_weights = sum(satellite_frames) / len(satellite_frames) * allocator_cfg.k_satellite

    raw_weights = core_weights + satellite_weights

    cap = allocator_cfg.gross_cap if effective_cap is None else effective_cap
    raw_gross = raw_weights.abs().sum(axis=1)
    if isinstance(cap, pd.Series):
        cap = cap.reindex(raw_gross.index)
    cap_scalar = (cap / raw_gross).clip(upper=1.0)
    # A sleeve dead on a given date (raw_gross == 0) leaves f undefined by
    # division; there is nothing to scale down, so treat it as unconstrained.
    cap_scalar = cap_scalar.where(raw_gross > 0, 1.0)

    scaled = raw_weights.mul(cap_scalar, axis=0)

    upper = pd.Series(allocator_cfg.max_position, index=columns)
    upper.loc[benchmark] = allocator_cfg.max_position_benchmark
    target_weights = scaled.clip(lower=-upper, upper=upper, axis=1)

    gross = target_weights.abs().sum(axis=1)
    net = target_weights.sum(axis=1)
    long_exposure = target_weights.clip(lower=0.0).sum(axis=1)
    short_exposure = (-target_weights.clip(upper=0.0)).sum(axis=1)

    prior = target_weights.shift(1).fillna(0.0)
    turnover = (target_weights - prior).abs().sum(axis=1)

    logger.info(
        "programme_book_combined",
        n_dates=len(target_weights),
        cap_binds_fraction=float((cap_scalar < 1.0).mean()),
        mean_gross=float(gross.mean()),
    )

    return Book(
        raw_weights=raw_weights,
        target_weights=target_weights,
        gross=gross,
        net=net,
        long_exposure=long_exposure,
        short_exposure=short_exposure,
        cap_scalar=cap_scalar,
        turnover=turnover,
        core_weights=core_weights,
        satellite_weights=satellite_weights,
        satellite_scalars=satellite_scalars,
    )


def financing_cost(book: Book, policy_rates: pd.Series, config: FinancingConfig) -> pd.Series:
    """Daily financing drag (spec §2.3, formula stated verbatim — do not simplify):

        daily = [ max(L - 1, 0) * (r + margin_spread)
                  + S * borrow_fee
                  - S * max(r - rebate_spread, 0) ] / trading_days

    L = book.long_exposure, S = book.short_exposure, r = policy_rates on that
    date. Positive means a cost. `test_financing_identity` recomputes this by
    hand and requires a match to 1e-12, so every term is left exactly as the
    spec writes it: `max(L - 1, 0)` (only leverage beyond 1x is margin-financed
    - the first dollar of long exposure needs no borrowed cash), `S * borrow_fee`
    (the whole short book pays a borrow fee), and a separate `S * max(r -
    rebate_spread, 0)` rebate credit (only paid when the policy rate exceeds the
    broker's spread on short proceeds).
    """
    r = policy_rates.reindex(book.gross.index).ffill()
    long_term = (book.long_exposure - 1.0).clip(lower=0.0) * (r + config.margin_spread)
    borrow_term = book.short_exposure * config.borrow_fee
    rebate_term = book.short_exposure * (r - config.rebate_spread).clip(lower=0.0)
    return (long_term + borrow_term - rebate_term) / config.trading_days


def transaction_cost(book: Book, config: CostConfig) -> pd.Series:
    """`book.turnover * one_way_bps / 10_000`. Positive is a cost.

    `test_cost_identity` asserts exactly this relation to 1e-12 — keep it a
    one-line product, no rounding or clipping.
    """
    return book.turnover * config.one_way_bps / 10_000.0


@dataclass(frozen=True)
class BookReturns:
    gross: pd.Series
    transaction_cost: pd.Series
    financing_cost: pd.Series
    net: pd.Series
    equity_curve: pd.Series  # (1 + net).cumprod()


def book_returns(
    book: Book,
    panel: object,
    policy_rates: pd.Series,
    config: ProgrammeConfig,
) -> BookReturns:
    """Apply the signal-to-trade lag once, to weights and costs alike (spec §2.4).

        gross(t) = (target_weights.shift(lag) * returns).sum(axis=1)
        net(t)   = gross(t) - transaction_cost.shift(lag) - financing_cost.shift(lag)

    Costs are shifted by the same lag as the weights: a cost is charged on the
    day the trade that caused it actually happens, not on the signal date. This
    is the ONLY place `book_returns` applies a shift — `financing_cost` and
    `transaction_cost` are computed above on the book's own (unlagged) date
    index and only shifted here, at the point they are combined with returns.

    `panel` is a `PricePanel` (data.py); only the cached `.returns` property is
    used, so a lightweight stand-in with that attribute also works (see the
    `combine` docstring for why — data.py does not exist in this worktree yet).
    """
    lag = config.execution.signal_to_trade_lag
    aligned_returns = panel.returns.reindex(columns=book.target_weights.columns)
    gross = (book.target_weights.shift(lag) * aligned_returns).sum(axis=1)

    txn_cost = transaction_cost(book, config.costs)
    fin_cost = financing_cost(book, policy_rates, config.financing)

    net = gross - txn_cost.shift(lag) - fin_cost.shift(lag)
    equity_curve = (1.0 + net.fillna(0.0)).cumprod()

    logger.info(
        "programme_book_returns",
        lag=lag,
        mean_gross=float(gross.mean()),
        mean_net=float(net.mean()),
    )

    return BookReturns(
        gross=gross,
        transaction_cost=txn_cost,
        financing_cost=fin_cost,
        net=net,
        equity_curve=equity_curve,
    )


def effective_breadth(sleeve_returns_frame: pd.DataFrame) -> float:
    """`(sum(lambda))**2 / sum(lambda**2)` over the eigenvalues of the sleeve
    return correlation matrix (spec §4.1). Ten independent sleeves would score
    10; the spec reports 4.05 (the spec's claim, not asserted here) and calls
    this the binding constraint on the programme's quality — most of the
    sleeve set is a small number of correlated bets wearing ten labels.
    """
    # Drop rows where any sleeve is still warming up. Sleeves reach full
    # history at different dates (S8 needs 63 days of holding on top of a
    # 21-day Amihud window; S5 needs 231), so a raw `.corr()` over the whole
    # frame produces NaN cells wherever two sleeves never overlapped — and
    # `eigvalsh` on a matrix containing NaN does not fail loudly, it fails as
    # "Eigenvalues did not converge", which reads like a numerical problem
    # rather than the missing-data problem it actually is.
    aligned = sleeve_returns_frame.dropna(how="any")
    # Drop zero-variance sleeves BEFORE correlating, not after. A sleeve that
    # never activated over the window — which happens whenever the panel is
    # shorter than that sleeve's warm-up, e.g. S3 needs a 504-day z-window and
    # S6 needs a 252-day beta window on top of a 231-day formation period —
    # has an undefined correlation with everything. Correlating first and
    # filtering after does not work: one dead sleeve puts a NaN in every other
    # sleeve's column, so a column-wise finite check then rejects all ten and
    # the answer silently becomes NaN.
    variances = aligned.std(ddof=1)
    aligned = aligned.loc[:, variances > 0]
    if len(aligned) < 2 or aligned.shape[1] < 2:
        return float("nan")
    corr = aligned.corr().to_numpy()
    if not np.isfinite(corr).all():
        return float("nan")
    eigenvalues = np.linalg.eigvalsh(corr)
    # Correlation-matrix eigenvalues are real and >= 0 up to float noise; clip
    # away any negative dust from near-singular inputs before summing.
    eigenvalues = np.clip(eigenvalues, 0.0, None)
    return float(eigenvalues.sum() ** 2 / (eigenvalues**2).sum())
