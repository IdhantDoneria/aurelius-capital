"""Thirteen circuit breakers, three severity tiers (spec section 10, Table 16).

This is the portfolio-level *daily* risk gate: one snapshot of the proposed
book (`RiskInputs`) goes in, one verdict (`RiskVerdict`) comes out. It is
deliberately **not** `mentisrex/risk/engine.py` or
`mentisrex/backtesting/risk/engine.py` — those are per-order pre-trade gates
for a different trading system; this module has no relationship to them
(spec ADDENDUM A.8).

Spec section 10 opens with this, and it is the reason every threshold below
is a hard number rather than something tuned for backtest performance:
"Every control in this section was tested as a return enhancer and rejected
... None of these controls improves the backtest. They exist because a
strategy that cannot be stopped is not a strategy, it is an exposure."
(spec section 10). The "in-sample firings" figures quoted in the comments
below are the spec's own reporting of how often each breaker fired in its
backtest — they are the spec's claim about its own history, not anything
measured by this code, and they carry no predictive weight for live firing
frequency.

`evaluate()` runs before any order is built (spec section 14.2, Table 27: the
risk gate sits at 15:35 ET, strictly before order construction at 15:42).
A HALT collapses `effective_cap` to 0.0, which is the actual mechanism that
turns "the book is halted" into "zero orders are generated" downstream —
there is no separate flag the caller has to remember to check.

Numeric core is float64 numpy/pandas throughout, per house convention
(ADDENDUM A.2); this module does no I/O and touches no database, so the
Decimal boundary never applies here.

CONTRACT-NOTE: two of the thirteen breakers (DATA_STALE, UNIVERSE_COLLAPSE)
key off thresholds that live on `UniverseConfig` (`max_staleness_days`,
`min_eligible_names`) in the contract's own config.py sketch, not on
`RiskConfig`. `RiskConfig` as specified carries no field for either. Rather
than reach into a different config section from a risk-gate function (or
silently invent a `RiskConfig` field the contract didn't ask for), this
module hard-codes the spec's own Table 16 numbers for those two breakers
(3 business days, 150 names — identical to `UniverseConfig`'s defaults) as
local constants, called out below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from mentisrex.programme.config import RAMP, ConfigError, RiskConfig

# spec Table 16: "Panel > 3 business days old" -> DATA_STALE. Not a RiskConfig
# field (see module CONTRACT-NOTE) — matches UniverseConfig.max_staleness_days.
_DATA_STALE_MAX_DAYS = 3

# spec Table 16 / Table 15: "Fewer than 150 eligible names" -> UNIVERSE_COLLAPSE.
# Not a RiskConfig field (see module CONTRACT-NOTE) — matches
# UniverseConfig.min_eligible_names.
_MIN_ELIGIBLE_NAMES = 150

# Trading-day annualisation constant used throughout the spec (matches
# FinancingConfig.trading_days' default); sleeve_health has no RiskConfig
# field for it since it is a market-calendar fact, not a tunable.
_TRADING_DAYS = 252

# sleeve_health must NEVER hand back a 0.0 multiplier (spec Table 15: "a
# sleeve at zero can never demonstrate recovery, and momentum's worst
# 12-month windows are historically followed by its best"). This is a floor
# of last resort in case a config override sets sleeve_health_multiplier to
# a non-positive value; the documented default (0.5) never needs it.
_SLEEVE_HEALTH_FLOOR = 0.01


class Severity(StrEnum):
    """A `str`-valued enum (contract section 7 specifies `class Severity(str,
    Enum)`; `enum.StrEnum` is the identical py312 spelling `ruff`'s UP042
    prefers — same `str` subclassing, same `.value`) so a `RiskVerdict`
    serialises straight into the JSON audit log."""

    SOFT = "SOFT"
    DERISK = "DERISK"
    HALT = "HALT"


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.SOFT: 0,
    Severity.DERISK: 1,
    Severity.HALT: 2,
}


@dataclass(frozen=True)
class Breach:
    """One fired breaker. `message` carries the spec's own action text so the
    operator reading the audit log knows what response the spec prescribes,
    not just that a threshold was crossed."""

    code: str
    severity: Severity
    message: str
    observed: float
    threshold: float


@dataclass(frozen=True)
class RiskVerdict:
    """The full result of one `evaluate()` call. `breaches` always lists every
    one of the thirteen checks that fired — evaluate() never short-circuits,
    so an operator staring at a HALT can still see every other thing that was
    also wrong that day."""

    breaches: tuple[Breach, ...]
    effective_cap: float
    halted: bool

    @property
    def severity(self) -> Severity | None:
        """Worst breach present: HALT beats DERISK beats SOFT. `None` if clean."""
        if not self.breaches:
            return None
        return max((b.severity for b in self.breaches), key=lambda s: _SEVERITY_RANK[s])

    @property
    def derisked(self) -> bool:
        """True iff the worst breach present is exactly DERISK (i.e. the derisk
        multiplier, not a halt, governs `effective_cap`)."""
        return self.severity == Severity.DERISK


@dataclass(frozen=True)
class RiskInputs:
    """One day's snapshot for the risk gate. Every field is something the
    caller has already computed (from the panel, the proposed book, or
    yesterday's reconciliation) — `evaluate()` does no computation of its
    own beyond thresholding these.

    `max_abs_position` — CONTRACT: the caller MUST exclude the benchmark
    column before computing this. The 20%/25% single-name limits exist to
    control idiosyncratic concentration risk (one company's accounting fraud
    taking part of the book with it); an index ETF carries no such risk, only
    market risk, which is governed by the gross cap and the drawdown budget
    instead (spec section 2.2 — this exact bug, applying the single-name cap
    to SPY, flat-lined the first production run at 3.2% CAGR regardless of
    leverage, and the spec calls fixing it worth more than any signal in the
    document). `evaluate()` has no way to know which column is the benchmark
    and cannot fix a value that arrives already wrong.
    """

    as_of: pd.Timestamp
    drawdown: float  # positive; 0.31 == 31% underwater
    daily_return: float  # signed; -0.06 == a 6% loss on the day
    realised_vol_21d: float
    proposed_gross: float
    proposed_net: float
    max_abs_position: float  # benchmark EXCLUDED by the caller, see above
    proposed_turnover: float
    n_eligible: int
    panel_staleness_days: int
    realised_cost_bps: float | None  # divergence from the modelled cost, in bps
    base_cap: float  # from the deployment ramp


BREAKER_CODES: tuple[str, ...] = (
    "DRAWDOWN_WARN",
    "DRAWDOWN_DERISK",
    "DRAWDOWN_HALT",
    "DAILY_LOSS_WARN",
    "DAILY_LOSS_HALT",
    "VOL_CEILING",
    "GROSS_HARD",
    "NET_HARD",
    "POSITION_HARD",
    "TURNOVER_SPIKE",
    "DATA_STALE",
    "UNIVERSE_COLLAPSE",
    "COST_DIVERGENCE",
)  # exactly 13, spec Table 16, same order as the table


def evaluate(inputs: RiskInputs, config: RiskConfig) -> RiskVerdict:
    """Evaluate all thirteen breakers, always, in Table 16's order. Pure: no
    I/O, no state mutation, no logging — this is a snapshot-in, verdict-out
    function, callable freely before any order is built (spec section 14.2,
    15:35 precedes order construction at 15:42).

    effective_cap = 0.0 if any HALT fired; else base_cap * derisk_multiplier
    if any DERISK fired; else base_cap. A HALT's zero cap is the entire
    mechanism by which "the book is halted" becomes "zero orders" downstream.
    """
    breaches: list[Breach] = []

    # DRAWDOWN_WARN — Table 16: drawdown >= 20% -> SOFT, "log and notify,
    # freeze any scheduled increase in the cap". Spec's claim: 5 episodes
    # in-sample.
    if inputs.drawdown >= config.drawdown_warn:
        breaches.append(
            Breach(
                "DRAWDOWN_WARN",
                Severity.SOFT,
                "Log and notify. Freeze any scheduled increase in the cap.",
                inputs.drawdown,
                config.drawdown_warn,
            )
        )

    # DRAWDOWN_DERISK — Table 16: drawdown >= 28% -> DERISK, "halve the
    # effective gross cap until the drawdown recovers below the trigger".
    # Spec's claim: 2 episodes in-sample.
    if inputs.drawdown >= config.drawdown_derisk:
        breaches.append(
            Breach(
                "DRAWDOWN_DERISK",
                Severity.DERISK,
                "Halve the effective gross cap until the drawdown recovers below the trigger.",
                inputs.drawdown,
                config.drawdown_derisk,
            )
        )

    # DRAWDOWN_HALT — Table 16: drawdown >= 34% -> HALT, "flatten to cash,
    # manual restart required, no automatic re-entry exists". Spec's claim:
    # 0 in-sample firings.
    if inputs.drawdown >= config.drawdown_halt:
        breaches.append(
            Breach(
                "DRAWDOWN_HALT",
                Severity.HALT,
                "Flatten to cash. Manual restart required. No automatic re-entry exists.",
                inputs.drawdown,
                config.drawdown_halt,
            )
        )

    # DAILY_LOSS_WARN — Table 16: one-day loss >= 5% -> SOFT, "log and
    # notify". Spec's claim: 11 days in-sample.
    if inputs.daily_return <= -config.daily_loss_warn:
        breaches.append(
            Breach(
                "DAILY_LOSS_WARN",
                Severity.SOFT,
                "Log and notify.",
                inputs.daily_return,
                -config.daily_loss_warn,
            )
        )

    # DAILY_LOSS_HALT — Table 16: one-day loss >= 10% -> HALT, "flatten,
    # same-night review before any restart". Spec's claim: 2 days in-sample
    # (Mar 2020).
    if inputs.daily_return <= -config.daily_loss_halt:
        breaches.append(
            Breach(
                "DAILY_LOSS_HALT",
                Severity.HALT,
                "Flatten. Same-night review before any restart.",
                inputs.daily_return,
                -config.daily_loss_halt,
            )
        )

    # VOL_CEILING — Table 16: 21-day realised vol > 45% -> DERISK, "halve the
    # effective cap". Spec's claim: 1 episode in-sample.
    if inputs.realised_vol_21d > config.vol_ceiling:
        breaches.append(
            Breach(
                "VOL_CEILING",
                Severity.DERISK,
                "Halve the effective cap.",
                inputs.realised_vol_21d,
                config.vol_ceiling,
            )
        )

    # GROSS_HARD — Table 16: proposed gross > 3.00x -> HALT, "flatten; this is
    # a software bug, not a market event, and must be treated as one". Spec's
    # claim: 0 in-sample firings.
    if inputs.proposed_gross > config.gross_hard:
        breaches.append(
            Breach(
                "GROSS_HARD",
                Severity.HALT,
                "Flatten. This is a software bug, not a market event, and must be treated as one.",
                inputs.proposed_gross,
                config.gross_hard,
            )
        )

    # NET_HARD — Table 16: |net| > 2.50x -> HALT, "flatten". Spec's claim: 0
    # in-sample firings. Compared on the absolute value per Table 16's own
    # "|Net|" notation.
    if abs(inputs.proposed_net) > config.net_hard:
        breaches.append(
            Breach(
                "NET_HARD",
                Severity.HALT,
                "Flatten.",
                abs(inputs.proposed_net),
                config.net_hard,
            )
        )

    # POSITION_HARD — Table 16: any single name > 25% -> HALT, "flatten".
    # Spec's claim: 0 in-sample firings (largest observed 1.4%). This is the
    # hard backstop breaker; it is distinct from AllocatorConfig.max_position
    # (20%), which is a softer, build-time cap applied during allocation.
    # See RiskInputs.max_abs_position docstring: the benchmark column MUST
    # already be excluded by the caller (spec section 2.2).
    if inputs.max_abs_position > config.position_hard:
        breaches.append(
            Breach(
                "POSITION_HARD",
                Severity.HALT,
                "Flatten.",
                inputs.max_abs_position,
                config.position_hard,
            )
        )

    # TURNOVER_SPIKE — Table 16: daily turnover > 60% of NAV -> DERISK, "hold
    # the order set for manual review". Spec's claim: 0 in-sample firings.
    if inputs.proposed_turnover > config.turnover_spike:
        breaches.append(
            Breach(
                "TURNOVER_SPIKE",
                Severity.DERISK,
                "Hold the order set for manual review.",
                inputs.proposed_turnover,
                config.turnover_spike,
            )
        )

    # DATA_STALE — Table 16: panel > 3 business days old -> HALT, "no orders,
    # never trade on old prices". Spec's claim: n/a (no firing count given).
    if inputs.panel_staleness_days > _DATA_STALE_MAX_DAYS:
        breaches.append(
            Breach(
                "DATA_STALE",
                Severity.HALT,
                "No orders. Never trade on old prices.",
                float(inputs.panel_staleness_days),
                float(_DATA_STALE_MAX_DAYS),
            )
        )

    # UNIVERSE_COLLAPSE — Table 16: fewer than 150 eligible names -> HALT, "no
    # orders". Spec's claim: 0 in-sample firings.
    if inputs.n_eligible < _MIN_ELIGIBLE_NAMES:
        breaches.append(
            Breach(
                "UNIVERSE_COLLAPSE",
                Severity.HALT,
                "No orders.",
                float(inputs.n_eligible),
                float(_MIN_ELIGIBLE_NAMES),
            )
        )

    # COST_DIVERGENCE — Table 16: realised cost > 5 bps from model -> SOFT,
    # "alert, re-derive expected Sharpe". Spec's claim: n/a. Skipped (not a
    # breach either way) when the caller has no realised-cost measurement yet.
    if (
        inputs.realised_cost_bps is not None
        and abs(inputs.realised_cost_bps) > config.cost_divergence_bps
    ):
        breaches.append(
            Breach(
                "COST_DIVERGENCE",
                Severity.SOFT,
                "Alert; re-derive expected Sharpe.",
                inputs.realised_cost_bps,
                config.cost_divergence_bps,
            )
        )

    breach_tuple = tuple(breaches)
    halted = any(b.severity == Severity.HALT for b in breach_tuple)
    derisked = any(b.severity == Severity.DERISK for b in breach_tuple)
    if halted:
        effective_cap = 0.0
    elif derisked:
        effective_cap = inputs.base_cap * config.derisk_multiplier
    else:
        effective_cap = inputs.base_cap

    return RiskVerdict(breaches=breach_tuple, effective_cap=effective_cap, halted=halted)


def sleeve_health(
    sleeve_returns: dict[str, pd.Series], as_of: pd.Timestamp, config: RiskConfig
) -> dict[str, float]:
    """Rolling 12-month (approximated as `_TRADING_DAYS` trading days) Sharpe
    per sleeve, evaluated at month-end. A sleeve whose trailing Sharpe is
    below `config.sleeve_health_sharpe` at `config.sleeve_health_months`
    consecutive month-ends (the most recent ones on or before `as_of`) is
    multiplied by `config.sleeve_health_multiplier`; everything else gets
    1.0.

    This function NEVER returns 0.0 for any sleeve (spec Table 15's own
    reasoning, quoted in the module docstring): "a sleeve at zero can never
    demonstrate recovery, and momentum's worst 12-month windows are
    historically followed by its best."

    A sleeve with fewer than `sleeve_health_months` observed month-ends on or
    before `as_of` (not enough live history to demonstrate three consecutive
    bad months) is treated as healthy — this function never de-risks on
    evidence it doesn't have.
    """
    result: dict[str, float] = {}
    for name, ret in sleeve_returns.items():
        ret = ret.sort_index()
        ret = ret.loc[ret.index <= as_of]
        if ret.empty:
            result[name] = 1.0
            continue

        rolling_mean = ret.rolling(_TRADING_DAYS, min_periods=_TRADING_DAYS).mean()
        rolling_std = ret.rolling(_TRADING_DAYS, min_periods=_TRADING_DAYS).std()
        rolling_sharpe = rolling_mean / rolling_std * math.sqrt(_TRADING_DAYS)

        month_end_sharpe = rolling_sharpe.groupby(rolling_sharpe.index.to_period("M")).last()
        recent = month_end_sharpe.tail(config.sleeve_health_months)

        unhealthy = (
            len(recent) == config.sleeve_health_months
            and recent.notna().all()
            and bool((recent < config.sleeve_health_sharpe).all())
        )
        result[name] = _health_multiplier(config) if unhealthy else 1.0
    return result


def _health_multiplier(config: RiskConfig) -> float:
    """Floor of last resort so a misconfigured (non-positive) multiplier can
    never actually zero out a sleeve. See `_SLEEVE_HEALTH_FLOOR`."""
    return (
        config.sleeve_health_multiplier
        if config.sleeve_health_multiplier > 0.0
        else (_SLEEVE_HEALTH_FLOOR)
    )


def deployment_cap(quarters_live: int, ramp: tuple[float, ...] = RAMP) -> float:
    """`ramp[min(quarters_live, len(ramp) - 1)]`, clamped below at 0 too so a
    caller passing a negative `quarters_live` gets the ramp's first rung
    rather than Python's negative-index wraparound.

    Spec section 10.2: the ramp is not optional and is enforced in code by
    reading persisted state (`ProgrammeState.quarters_live`), because
    starting at the target cap means the first drawdown arrives before there
    is any live evidence to judge it against.
    """
    if not ramp:
        raise ConfigError("deployment_cap: ramp must be non-empty", detail=f"ramp={ramp!r}")
    index = min(max(quarters_live, 0), len(ramp) - 1)
    return ramp[index]
