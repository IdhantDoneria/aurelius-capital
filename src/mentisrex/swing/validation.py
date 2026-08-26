"""Robustness testing.

A short-horizon backtest is easy to make look good and hard to believe, so
the checks here are the ones that break strategies rather than the ones that
confirm them:

  * walk-forward, so no parameter is chosen with knowledge of the period it
    is scored on;
  * subperiod, so a single regime cannot carry the record;
  * parameter sensitivity, because an edge that exists only at one setting is
    a fitted artefact;
  * cost sensitivity and a breakeven multiple, because the spread here is
    modelled rather than measured;
  * a signal-decay curve, which tells you whether you are early or lucky;
  * a stationary bootstrap, for a distribution rather than a point estimate.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .metrics import Performance, deflated_sharpe, evaluate, newey_west_t, stationary_bootstrap


@dataclass
class SubperiodResult:
    label: str
    perf: Performance


def subperiods(
    returns: pd.Series,
    *,
    benchmark: pd.Series | None = None,
    rf: pd.Series | None = None,
    by: str = "YE",
) -> pd.DataFrame:
    """Performance broken out by calendar period."""
    rows = {}
    for label, g in returns.groupby(pd.Grouper(freq=by)):
        if len(g) < 40:
            continue
        b = benchmark.reindex(g.index) if benchmark is not None else None
        r = rf.reindex(g.index) if rf is not None else None
        rows[str(label.date())] = evaluate(g, benchmark=b, rf=r).to_dict()
    return pd.DataFrame(rows).T


def regime_split(
    returns: pd.Series, conditioner: pd.Series, *, n_buckets: int = 3, labels: Sequence[str] | None = None
) -> pd.DataFrame:
    """Performance conditioned on a state variable, e.g. the VIX.

    Bucket edges use the conditioner's *expanding* quantiles so that a day is
    classified using only the history available at the time; classifying with
    full-sample quantiles would leak the future into the regime label.
    """
    c = conditioner.reindex(returns.index).ffill()
    q = pd.DataFrame({f"q{i}": c.expanding(min_periods=250).quantile(i / n_buckets)
                      for i in range(1, n_buckets)})
    bucket = pd.Series(0, index=returns.index, dtype=int)
    for i in range(1, n_buckets):
        bucket += (c > q[f"q{i}"]).astype(int)
    bucket = bucket.where(q.notna().all(axis=1))
    names = list(labels) if labels else [f"bucket_{i}" for i in range(n_buckets)]

    rows = {}
    for i, nm in enumerate(names):
        g = returns[bucket == i]
        if len(g) < 40:
            continue
        rows[nm] = {
            "n_days": len(g),
            "mean_ann": float(g.mean() * 252),
            "vol_ann": float(g.std(ddof=1) * np.sqrt(252)),
            "sharpe": float(g.mean() / g.std(ddof=1) * np.sqrt(252)) if g.std(ddof=1) > 0 else np.nan,
            "hit_rate": float((g > 0).mean()),
            "nw_t": newey_west_t(g),
        }
    return pd.DataFrame(rows).T


def walk_forward(
    run_fn: Callable[[dict, pd.DatetimeIndex], pd.Series],
    grid: list[dict],
    dates: pd.DatetimeIndex,
    *,
    train_years: int = 3,
    test_years: int = 1,
    objective: Callable[[pd.Series], float] | None = None,
) -> tuple[pd.Series, pd.DataFrame]:
    """Anchored walk-forward: choose parameters on the training window, score
    on the immediately following test window, splice the test windows.

    Returns the spliced out-of-sample return series and a table recording
    what was chosen in each fold and how it then performed.
    """
    objective = objective or (
        lambda r: float(r.mean() / r.std(ddof=1) * np.sqrt(252)) if r.std(ddof=1) > 0 else -np.inf
    )
    folds, oos = [], []
    anchor = dates[0]
    train_end = anchor + pd.DateOffset(years=train_years)
    last = dates[-1] + pd.Timedelta(days=1)

    while train_end < last:
        test_end = min(train_end + pd.DateOffset(years=test_years), last)
        # Anchored: the training window always starts at the beginning of the
        # sample and grows. The *test* window advances by its own length, so
        # consecutive tests tile the timeline exactly once -- advancing by the
        # training length instead would silently drop the years in between
        # from the out-of-sample record.
        tr = dates[(dates >= anchor) & (dates < train_end)]
        te = dates[(dates >= train_end) & (dates < test_end)]
        if len(tr) < 200 or len(te) < 40:
            break

        # Ties break toward the *earlier* grid entry. `max` over (score, index)
        # tuples breaks toward the later one, which silently makes an inert
        # parameter look as though it were being chosen deliberately in every
        # fold. Grids here are ordered simplest-first, so this is a parsimony
        # rule rather than an arbitrary one.
        scored = [(objective(run_fn(p, tr)), -i, i) for i, p in enumerate(grid)]
        best_score, _, best_i = max(scored)
        te_ret = run_fn(grid[best_i], te)
        oos.append(te_ret)
        folds.append(
            {
                "train_start": tr[0].date(), "train_end": tr[-1].date(),
                "test_start": te[0].date(), "test_end": te[-1].date(),
                "n_train": len(tr), "n_test": len(te),
                "chosen": str(grid[best_i]), "train_obj": best_score,
                "test_obj": objective(te_ret),
            }
        )
        train_end = test_end
    return (pd.concat(oos) if oos else pd.Series(dtype=float)), pd.DataFrame(folds)


def parameter_sensitivity(
    run_fn: Callable[[dict], pd.Series], grid: list[dict]
) -> pd.DataFrame:
    """Score every point on a parameter grid.

    The number that matters is not the best cell but the *spread* across
    cells: a signal whose Sharpe collapses off its optimum is a curve fit.
    """
    rows = []
    for params in grid:
        r = run_fn(params)
        p = evaluate(r)
        rows.append({**params, "sharpe": p.sharpe, "cagr": p.cagr,
                     "max_dd": p.max_drawdown, "nw_t": newey_west_t(r)})
    return pd.DataFrame(rows)


def cost_sensitivity(
    run_fn: Callable[[float], pd.Series], multiples: Sequence[float] = (0.5, 1.0, 2.0, 3.0, 4.0, 6.0)
) -> pd.DataFrame:
    rows = []
    for m in multiples:
        r = run_fn(m)
        p = evaluate(r)
        rows.append({"cost_multiple": m, "cagr": p.cagr, "sharpe": p.sharpe,
                     "max_dd": p.max_drawdown})
    return pd.DataFrame(rows)


def breakeven_cost_multiple(table: pd.DataFrame, metric: str = "sharpe") -> float:
    """Cost multiple at which the strategy stops beating cash.

    Defaults to the **Sharpe** column, not CAGR. Since the simulator credits
    interest on unencumbered cash, a CAGR-based breakeven asks the wrong
    question: it finds the point at which the book stops making money at all,
    which for a capacity-constrained sleeve holding mostly Treasury bills is
    far beyond the point at which it stopped being worth running. Sharpe
    crosses zero exactly where excess return does.

    Reported alongside every headline number: a strategy that only beats cash
    below a third of modelled costs has no margin for the cost model being
    wrong, which for a modelled spread is the relevant question.
    """
    t = table.sort_values("cost_multiple")
    x, y = t["cost_multiple"].to_numpy(), t[metric].to_numpy()
    for i in range(len(x) - 1):
        if y[i] > 0 >= y[i + 1]:
            return float(x[i] + (x[i + 1] - x[i]) * y[i] / (y[i] - y[i + 1]))
    return float(x[-1]) if y[-1] > 0 else float(x[0])


def signal_decay(
    score: np.ndarray, fwd_returns: np.ndarray, horizons: Sequence[int] = (1, 2, 3, 5, 10, 21)
) -> pd.DataFrame:
    """Rank information coefficient of the score against forward returns at a
    range of horizons.

    The shape is diagnostic. A signal that peaks at one day and is gone by
    three is a microstructure effect and will not survive costs; one that
    holds out to a week or two can be traded.
    """
    rows = []
    T, _ = score.shape
    for h in horizons:
        ics = []
        for t in range(T - h):
            s, f = score[t], fwd_returns[t : t + h].sum(axis=0)
            m = np.isfinite(s) & np.isfinite(f) & (s != 0)
            if m.sum() < 30:
                continue
            sr = pd.Series(s[m]).rank()
            fr = pd.Series(f[m]).rank()
            c = np.corrcoef(sr, fr)[0, 1]
            if np.isfinite(c):
                ics.append(c)
        if not ics:
            continue
        a = np.asarray(ics)
        rows.append(
            {
                "horizon_days": h, "mean_ic": a.mean(), "ic_std": a.std(ddof=1),
                "ic_ir": a.mean() / a.std(ddof=1) if a.std(ddof=1) > 0 else np.nan,
                "t_stat": a.mean() / (a.std(ddof=1) / np.sqrt(len(a))),
                "n_obs": len(a),
            }
        )
    return pd.DataFrame(rows)


def full_report(
    returns: pd.Series,
    *,
    benchmark: pd.Series,
    rf: pd.Series,
    n_trials: int,
    vix: pd.Series | None = None,
    n_paths: int = 4000,
) -> dict:
    perf = evaluate(returns, benchmark=benchmark, rf=rf)
    boot = stationary_bootstrap(returns, n_paths=n_paths, mean_block=10)
    dsr, sr0 = deflated_sharpe(perf.sharpe, returns, n_trials=n_trials)
    out = {
        "performance": perf.to_dict(),
        "newey_west_t": newey_west_t(returns),
        "deflated_sharpe": dsr,
        "deflation_benchmark_sharpe": sr0,
        "bootstrap": {
            "sharpe_p05": float(boot["sharpe"].quantile(0.05)),
            "sharpe_median": float(boot["sharpe"].median()),
            "sharpe_p95": float(boot["sharpe"].quantile(0.95)),
            "prob_sharpe_below_zero": float((boot["sharpe"] < 0).mean()),
            "maxdd_p05": float(boot["max_drawdown"].quantile(0.05)),
            "maxdd_median": float(boot["max_drawdown"].median()),
        },
        "annual": subperiods(returns, benchmark=benchmark, rf=rf).to_dict("index"),
    }
    if vix is not None:
        out["vix_regime"] = regime_split(
            returns, vix, n_buckets=3, labels=("low_vol", "mid_vol", "high_vol")
        ).to_dict("index")
    return out
