"""Live-versus-backtest divergence, and the pre-committed kill criteria (spec
Table 26's `monitor.py` row: "Volatility, turnover, gross and beta -- not
return").

Return is deliberately excluded from the comparison. It is too noisy over any
horizon short enough to be actionable -- a live Sharpe estimate needs years to
separate model decay from ordinary variance (spec section 13.1's own 2.46-year
mean time to recognise loss makes the point). Volatility, turnover, gross and
beta are different in kind: a book running the wrong realised volatility, the
wrong turnover, or a drifted beta is a sizing fault, a signal-behaviour
fault, or a data fault -- each detectable in weeks, each actionable the
moment it is seen. This module watches the things that are fast to diagnose
and cheap to fix, and leaves the slow, noisy question of "is the edge still
there" to the multi-year reviews spec Table 28 already schedules.

`monitor()` evaluates three of spec Table 25's six pre-committed kill
criteria directly, because those three are exactly what its fixed signature
carries: realised volatility outside 18-36% (over whatever window of
`live_returns` the caller passes -- Table 25 specifies 6 months), realised
turnover outside 25-60x NAV annualised, and realised beta outside 0.6-1.7
(passed in pre-computed, since Table 25's window for beta is 12 months and
this function receives no per-name returns to derive beta from itself). It
also reports a GROSS divergence against the backtest-expected figure, using
the +/-0.35x tolerance spec Table 28 names for the weekly gross-exposure
review -- gross is not itself one of Table 25's six kill criteria, but Table
26 names it as one of the four things this module compares.

CONTRACT-NOTE: the other three Table 25 kill criteria cannot be evaluated by
`monitor()` as signed -- its parameters do not carry the data they need.
Recorded here rather than silently dropped:
  - "Realised cost above 12 bps one-way for a full quarter" needs a cost
    history; this module receives no cost series. The natural home for a
    realised-cost check is `risk.py`'s COST_DIVERGENCE breaker
    (`RiskInputs.realised_cost_bps` against `RiskConfig.cost_divergence_bps`),
    which already exists for the daily case. This quarter-long governance
    version needs a rolling cost-history input that nothing in this contract
    currently produces and stores -- unblocked by extending `state.py` (or
    the audit log it already writes) to retain realised cost per day.
  - "Mean sleeve correlation above 0.5" is exactly what `crowding_monitor()`
    below computes, but as a raw correlation series, not a fired/not-fired
    verdict -- `monitor()` receives no sleeve returns to compute it from.
    The caller (`cli.py`, not built in this delivery) is responsible for
    calling `crowding_monitor()` alongside `monitor()` and checking its
    latest value against 0.5.
  - "Three consecutive years below a 0.3 Sharpe" needs multi-year annual
    Sharpe history, which no module in this contract persists yet.
    Unblocked by extending `state.py` to retain a per-year realised Sharpe,
    which does not exist today.
A kill criterion this module cannot check says so here rather than reporting
false comfort by omission.

Both `monitor()` and `crowding_monitor()` are pure and never raise: missing
or insufficient input produces a report/series that says a metric was not
evaluated (`NaN`, or an empty result, always logged) rather than a crash or
a silent "no breach."

Numeric core is float64 pandas/numpy, per house convention (see
`mentisrex/programme/config.py`'s module docstring) -- this is a monitoring
report, not the ledger.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import combinations

import pandas as pd

from mentisrex.core.logging import get_logger
from mentisrex.programme.config import SATELLITE_SLEEVES, ProgrammeConfig

logger = get_logger(__name__)

# spec Table 25: pre-committed acceptable bands, the three this signature can check.
_VOLATILITY_RANGE = (0.18, 0.36)  # over any 6 months
_TURNOVER_RANGE = (25.0, 60.0)  # x NAV annualised
_BETA_RANGE = (0.6, 1.7)  # over any 12 months

# Divergence tolerances: half the Table 25 band width for vol/turnover/beta;
# spec Table 28's explicit weekly-review figure for gross.
_VOLATILITY_TOLERANCE = (_VOLATILITY_RANGE[1] - _VOLATILITY_RANGE[0]) / 2
_TURNOVER_TOLERANCE = (_TURNOVER_RANGE[1] - _TURNOVER_RANGE[0]) / 2
_BETA_TOLERANCE = (_BETA_RANGE[1] - _BETA_RANGE[0]) / 2
_GROSS_TOLERANCE = 0.35  # spec Table 28: "gross outside +/-0.35x"


@dataclass(frozen=True)
class Divergence:
    """One metric's live value against what the backtest expected."""

    metric: str
    live: float
    expected: float
    tolerance: float
    breached: bool


@dataclass(frozen=True)
class MonitorReport:
    as_of: pd.Timestamp
    divergences: tuple[Divergence, ...]
    kill_criteria_fired: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.kill_criteria_fired and not any(d.breached for d in self.divergences)


def _series_last_valid(*series: pd.Series | None) -> pd.Timestamp:
    """Deterministic `as_of` for a report: the latest date any input series
    actually has a row on. `monitor()` has no `as_of` parameter, and a
    monitoring function must stay pure -- no wall-clock fallback."""
    ends = [s.index[-1] for s in series if s is not None and len(s) > 0]
    return max(ends) if ends else pd.NaT


def _divergence(
    metric: str, live_value: float, tolerance: float, expected: Mapping[str, float]
) -> Divergence:
    """Build one Divergence entry. A missing `expected[metric]` or a NaN
    `live_value` cannot be assessed for breach; both are logged, and the
    entry comes back with `breached=False` and NaN on whichever side is
    unavailable -- the report shows "not evaluated", never a fabricated
    pass."""
    expected_value = expected.get(metric)
    live_missing = live_value is None or math.isnan(live_value)
    if live_missing:
        logger.warning("programme_monitor_missing_live_value", metric=metric)
    if expected_value is None:
        logger.warning("programme_monitor_missing_expected_value", metric=metric)
        return Divergence(
            metric=metric,
            live=float("nan") if live_missing else live_value,
            expected=float("nan"),
            tolerance=tolerance,
            breached=False,
        )
    if live_missing:
        return Divergence(
            metric=metric,
            live=float("nan"),
            expected=float(expected_value),
            tolerance=tolerance,
            breached=False,
        )
    breached = abs(live_value - float(expected_value)) > tolerance
    return Divergence(
        metric=metric,
        live=live_value,
        expected=float(expected_value),
        tolerance=tolerance,
        breached=breached,
    )


def monitor(
    live_returns: pd.Series,
    live_gross: pd.Series,
    live_turnover: pd.Series,
    live_beta: float,
    expected: Mapping[str, float],
    config: ProgrammeConfig,
) -> MonitorReport:
    """Compare live volatility, turnover, gross and beta against what the
    backtest expected, and fire whichever of spec Table 25's kill criteria
    this signature can evaluate (see the module docstring's CONTRACT-NOTE for
    the three it cannot). `expected` keys are `"volatility"`, `"turnover"`,
    `"gross"`, `"beta"`; a missing key means that metric is not evaluated.

    `live_returns` should already be windowed by the caller to the horizon
    spec Table 25 specifies for volatility (6 months); `live_beta` is
    expected already computed over its 12-month window, since this function
    receives no per-name returns to derive beta from itself. `live_turnover`
    is a daily one-way-turnover-as-fraction-of-NAV series; it is annualised
    here as `mean * config.financing.trading_days`.
    """
    trading_days = config.financing.trading_days
    live_vol = (
        float(live_returns.std(ddof=1) * math.sqrt(trading_days))
        if live_returns is not None and live_returns.size >= 2
        else float("nan")
    )
    live_turnover_annualised = (
        float(live_turnover.mean() * trading_days)
        if live_turnover is not None and live_turnover.size >= 1
        else float("nan")
    )
    live_gross_mean = (
        float(live_gross.mean())
        if live_gross is not None and live_gross.size >= 1
        else float("nan")
    )
    live_beta_value = (
        float(live_beta) if live_beta is not None and not math.isnan(live_beta) else float("nan")
    )

    divergences = (
        _divergence("volatility", live_vol, _VOLATILITY_TOLERANCE, expected),
        _divergence("turnover", live_turnover_annualised, _TURNOVER_TOLERANCE, expected),
        _divergence("gross", live_gross_mean, _GROSS_TOLERANCE, expected),
        _divergence("beta", live_beta_value, _BETA_TOLERANCE, expected),
    )

    fired: list[str] = []
    if not math.isnan(live_vol) and not (_VOLATILITY_RANGE[0] <= live_vol <= _VOLATILITY_RANGE[1]):
        fired.append("VOLATILITY_OUT_OF_RANGE")
    if not math.isnan(live_turnover_annualised) and not (
        _TURNOVER_RANGE[0] <= live_turnover_annualised <= _TURNOVER_RANGE[1]
    ):
        fired.append("TURNOVER_OUT_OF_RANGE")
    if not math.isnan(live_beta_value) and not (
        _BETA_RANGE[0] <= live_beta_value <= _BETA_RANGE[1]
    ):
        fired.append("BETA_OUT_OF_RANGE")

    as_of = _series_last_valid(live_returns, live_gross, live_turnover)
    report = MonitorReport(
        as_of=as_of,
        divergences=divergences,
        kill_criteria_fired=tuple(fired),
    )
    logger.info(
        "programme_monitor",
        as_of=str(as_of),
        kill_criteria_fired=list(report.kill_criteria_fired),
        n_breached=sum(d.breached for d in report.divergences),
        ok=report.ok,
    )
    return report


def crowding_monitor(sleeve_returns: dict[str, pd.Series], window: int = 60) -> pd.Series:
    """Rolling mean pairwise correlation among the six SATELLITE sleeves
    (spec section 15.4). Above roughly 0.5 the diversification the satellite
    layer depends on has stopped working -- the August 2024 yen-carry unwind
    (spec section 8.2: "crowded-factor unwind: lost 1.9x the index") is this
    signature playing out; this is the cheap, always-on early warning for it.

    Filters `sleeve_returns` to `SATELLITE_SLEEVES` first, so passing the
    full ten-sleeve dict is safe. Fewer than two satellite sleeves present
    means there is nothing to correlate -- logged, and an empty Series is
    returned rather than a crash or a fabricated 0.0.
    """
    if not sleeve_returns:
        logger.warning("programme_crowding_monitor_no_sleeve_returns")
        return pd.Series(dtype=float)

    available = [name for name in SATELLITE_SLEEVES if name in sleeve_returns]
    if len(available) < 2:
        logger.warning(
            "programme_crowding_monitor_insufficient_sleeves",
            n_available=len(available),
            available=available,
        )
        return pd.Series(dtype=float)

    pairwise_corr = []
    for name_a, name_b in combinations(available, 2):
        series_a, series_b = sleeve_returns[name_a].align(sleeve_returns[name_b], join="outer")
        pairwise_corr.append(series_a.rolling(window=window, min_periods=window).corr(series_b))

    mean_corr = pd.concat(pairwise_corr, axis=1).mean(axis=1, skipna=True)
    return mean_corr.sort_index()
