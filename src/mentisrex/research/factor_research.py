"""Factor-research campaign layer (M34, §XI).

Turns the single-cross-section primitives of `cross_sectional` (M32) into a full
multi-date factor evaluation: the IC time series, its IR and HAC-robust t-stat
(M31), the long-short quantile-spread return series and its Sharpe/significance,
the quantile return profile with monotonicity, and factor turnover.

Design is dict-based per date — signal and forward-return cross-sections keyed by
security id — because a PIT universe changes membership across dates. Names are
aligned pairwise per date (present in both signal and forward return); missing
names are dropped, never imputed. Pure/deterministic; composes existing engines.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from mentisrex.research.cross_sectional import (
    information_coefficient,
    neutralize,
    percentile_rank,
    quantile_spread,
)
from mentisrex.research.validation.hac import hac_significance
from mentisrex.research.validation.significance import sharpe, significance


def _align(signal: dict, fwd: dict, groups: dict | None, covariates: dict | None):
    """Common keys present in signal and fwd (and groups/covariates if given),
    returned as ordered aligned arrays. Order is by key for determinism."""
    keys = set(signal) & set(fwd)
    if groups is not None:
        keys &= set(groups)
    if covariates is not None:
        keys &= set(covariates)
    keys = sorted(keys)
    s = np.array([signal[k] for k in keys], dtype=float)
    f = np.array([fwd[k] for k in keys], dtype=float)
    g = np.array([groups[k] for k in keys], dtype=object) if groups is not None else None
    c = np.array([covariates[k] for k in keys], dtype=float) if covariates is not None else None
    return keys, s, f, g, c


@dataclass
class FactorReport:
    n_periods: int
    avg_breadth: float
    ic_series: list = field(default_factory=list)
    ic_mean: float = float("nan")
    ic_std: float = float("nan")
    ic_ir: float = float("nan")  # IC information ratio = mean/std
    ic_t_stat: float = float("nan")  # HAC t-stat of the IC series (M31)
    ic_p_value: float = float("nan")
    ic_hit_rate: float = float("nan")  # fraction of periods IC has the mean's sign
    ls_return_series: list = field(default_factory=list)
    ls_sharpe: float = float("nan")
    ls_t_stat: float = float("nan")  # HAC t-stat of the long-short series
    ls_p_value: float = float("nan")
    quantile_profile: list = field(default_factory=list)  # avg fwd return per bucket
    monotonic_fraction: float = float("nan")
    turnover: float = float("nan")  # avg fraction of long book replaced
    ls_turnover_series: list = field(default_factory=list)  # two-way per rebalance
    # net-of-cost (populated only when a cost_model is supplied)
    net_ls_return_series: list = field(default_factory=list)
    net_ls_sharpe: float = float("nan")
    net_ls_t_stat: float = float("nan")
    cost_bps_per_period: float = float("nan")

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        return d


def evaluate_factor(
    signals: list[dict],
    forward_returns: list[dict],
    *,
    groups: list[dict] | None = None,
    covariates: list[dict] | None = None,
    q: int = 5,
    ic_method: str = "spearman",
    periods_per_year: int = 12,
    neutralize_signal: bool = False,
    cost_model=None,
) -> FactorReport:
    """Evaluate a factor over a sequence of aligned cross-sections.

    signals[t], forward_returns[t]: dict security_id -> value for rebalance date t.
    groups[t]/covariates[t]: optional per-date neutralization inputs. When
    `neutralize_signal` is set, the signal is residualized on them before scoring
    (sector/beta/vol-neutral factor). Long = top quantile, short = bottom; turnover
    is the average one-way fraction of a book replaced between consecutive dates.
    When `cost_model` (a TransactionCostModel) is given, a net-of-cost long-short
    series and its Sharpe/HAC-t are also produced (linear bps × two-way turnover).
    """
    if len(signals) != len(forward_returns):
        raise ValueError("signals and forward_returns must have equal length")
    T = len(signals)

    ic_series: list[float] = []
    ls_series: list[float] = []
    bucket_acc = np.zeros(q)
    bucket_cnt = np.zeros(q)
    mono_hits = 0
    mono_total = 0
    breadths: list[int] = []
    prev_long: set | None = None
    prev_short: set | None = None
    ls_turnover: list[float] = []  # two-way, aligned to ls_series periods

    for t in range(T):
        g = groups[t] if groups is not None else None
        c = covariates[t] if covariates is not None else None
        keys, s, f, garr, carr = _align(signals[t], forward_returns[t], g, c)
        if s.size < 2:
            continue
        if neutralize_signal and (garr is not None or carr is not None):
            s = neutralize(s, groups=garr, covariates=carr)
        breadths.append(int(np.isfinite(s).sum()))

        ic = information_coefficient(s, f, method=ic_method)
        if ic == ic:
            ic_series.append(ic)

        qs = quantile_spread(s, f, q=q)
        for i, b in enumerate(qs["buckets"]):
            if b == b:
                bucket_acc[i] += b
                bucket_cnt[i] += 1
        if qs["buckets"]:
            mono_total += 1
            mono_hits += 1 if qs["monotonic"] else 0

        # long = top quantile, short = bottom quantile; two-way turnover vs prev
        pr = percentile_rank(s)
        long_names = {keys[i] for i in range(len(keys)) if pr[i] == pr[i] and pr[i] >= (q - 1) / q}
        short_names = {keys[i] for i in range(len(keys)) if pr[i] == pr[i] and pr[i] < 1.0 / q}

        if qs["long_short"] == qs["long_short"]:
            ls_series.append(qs["long_short"])
            long_repl = (
                1.0 - len(long_names & prev_long) / len(long_names)
                if prev_long is not None and long_names
                else 1.0
            )
            short_repl = (
                1.0 - len(short_names & prev_short) / len(short_names)
                if prev_short is not None and short_names
                else 1.0
            )
            ls_turnover.append(long_repl + short_repl)  # two-way (both legs)

        if long_names:
            prev_long = long_names
        if short_names:
            prev_short = short_names

    ic_arr = np.array(ic_series, dtype=float)
    ls_arr = np.array(ls_series, dtype=float)

    rep = FactorReport(
        n_periods=len(list(breadths)),
        avg_breadth=float(np.mean(breadths)) if breadths else 0.0,
        ic_series=ic_series,
        ls_return_series=ls_series,
        quantile_profile=[
            float(bucket_acc[i] / bucket_cnt[i]) if bucket_cnt[i] else float("nan")
            for i in range(q)
        ],
        monotonic_fraction=float(mono_hits / mono_total) if mono_total else float("nan"),
        turnover=float(np.mean([x / 2.0 for x in ls_turnover[1:]]))
        if len(ls_turnover) > 1
        else float("nan"),
        ls_turnover_series=ls_turnover,
    )

    if ic_arr.size >= 2:
        rep.ic_mean = float(ic_arr.mean())
        rep.ic_std = float(ic_arr.std(ddof=1))
        rep.ic_ir = float(rep.ic_mean / rep.ic_std) if rep.ic_std > 0 else 0.0
        rep.ic_hit_rate = float(np.mean(np.sign(ic_arr) == np.sign(rep.ic_mean)))
        h = hac_significance(ic_arr)  # autocorrelation-robust IC t-stat (M31)
        rep.ic_t_stat, rep.ic_p_value = h["hac_t_stat"], h["hac_p_value"]

    if ls_arr.size >= 2:
        rep.ls_sharpe = sharpe(ls_arr, periods=periods_per_year)
        _ = significance(ls_arr)  # ensures HAC fields computed identically
        h = hac_significance(ls_arr)
        rep.ls_t_stat, rep.ls_p_value = h["hac_t_stat"], h["hac_p_value"]

        if cost_model is not None:
            # per-period cost = linear_bps * two-way traded fraction of gross.
            # Assumes equal-weight long and short legs; impact term omitted (needs
            # per-name notionals/ADV — supplied by the backtest layer, not the IC panel).
            lin = cost_model.linear_bps() / 1e4
            tw = np.array(ls_turnover[: ls_arr.size], dtype=float)
            costs = lin * tw
            net = ls_arr - costs
            rep.net_ls_return_series = [float(x) for x in net]
            rep.net_ls_sharpe = sharpe(net, periods=periods_per_year)
            rep.net_ls_t_stat = hac_significance(net)["hac_t_stat"]
            rep.cost_bps_per_period = float(costs.mean() * 1e4)

    return rep


def ic_decay(
    signals: list[dict],
    forward_returns_by_horizon: list[list[dict]],
    *,
    ic_method: str = "spearman",
) -> dict:
    """Mean IC of a signal against forward returns at each horizon. A decaying
    curve => a short-lived edge; a flat/rising curve => longer persistence.
    `forward_returns_by_horizon[h]` is the per-date forward-return panel at horizon h.
    """
    out = {}
    for h, fwd_panels in enumerate(forward_returns_by_horizon, start=1):
        ics = []
        for sig, fwd in zip(signals, fwd_panels, strict=False):
            _keys, s, f, _, _ = _align(sig, fwd, None, None)
            if s.size >= 2:
                ic = information_coefficient(s, f, method=ic_method)
                if ic == ic:
                    ics.append(ic)
        out[h] = float(np.mean(ics)) if ics else float("nan")
    return out
