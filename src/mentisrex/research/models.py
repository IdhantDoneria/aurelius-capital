"""Value types for the research framework + the statistics that gate a verdict.

Kept free of engine/store imports so the guard logic is pure and unit-testable.
"""

from __future__ import annotations

import enum
import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime


class Verdict(enum.StrEnum):
    ACCEPT = "accept"  # survives OOS + significance + fragility guards
    REJECT = "reject"  # failed at least one guard; capital protected
    INCONCLUSIVE = "inconclusive"  # not enough evidence to decide


@dataclass(frozen=True)
class Hypothesis:
    id: str
    statement: str
    rationale: str
    researcher: str
    created_at: datetime
    status: str = "open"  # open | confirmed | rejected


@dataclass(frozen=True)
class ValidationCriteria:
    """Acceptance thresholds. Calibration knobs — tune per asset class / desk."""

    min_oos_sharpe: float = 0.5
    max_is_oos_decay: float = 0.5  # OOS Sharpe must be >= (1 - decay) * IS Sharpe
    # min_trades defaults to 0 (informational): the Phase-4 round-trip reconstruction
    # only matches long cycles, so it undercounts short/hold strategies. The Sharpe
    # floor already rejects genuinely inactive strategies. Raise per desk if wanted.
    min_trades: int = 0
    max_param_cv: float = 0.75  # OOS-metric coeff of variation across the grid
    significance_alpha: float = 0.05  # after multiple-testing correction
    min_oos_observations: int = 30  # below this -> INCONCLUSIVE, not a verdict


@dataclass
class SensitivityResult:
    metric: str
    results: list[tuple[dict, float]]  # (params, oos metric)
    mean: float
    std: float
    cv: float  # abs(std / mean); fragility proxy
    best_params: dict
    worst_params: dict


@dataclass
class ValidationReport:
    verdict: Verdict
    reasons: list[str]
    is_sharpe: float
    oos_sharpe: float
    oos_return: float
    oos_max_drawdown: float
    oos_trades: int
    n_trials: int
    adjusted_pvalue: float
    param_cv: float | None = None
    checks: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentRecord:
    id: str
    hypothesis_id: str
    researcher: str
    created_at: datetime
    dataset_version: str
    strategy_name: str
    strategy_version: int
    features_used: list[str]
    params: dict
    report: ValidationReport
    config_snapshot: dict = field(default_factory=dict)


# ── statistics ────────────────────────────────────────────────────────────────


def _norm_sf(x: float) -> float:
    """Upper-tail standard normal, 1 - Phi(x). No scipy."""
    return 0.5 * math.erfc(x / math.sqrt(2))


def sharpe_pvalue(sharpe_ann: float, n_obs: int, trading_days: int = 252) -> float:
    """One-sided p-value for H0: true Sharpe <= 0, from an annualized Sharpe.

    t-stat of a Sharpe estimate ~ SR_per_period * sqrt(n_obs). We de-annualize
    the annual Sharpe, form the t-stat, and read the normal upper tail.
    """
    if n_obs < 2 or sharpe_ann <= 0:
        return 1.0
    sr_per_period = sharpe_ann / math.sqrt(trading_days)
    t = sr_per_period * math.sqrt(n_obs)
    return _norm_sf(t)


def bonferroni(pvalue: float, n_trials: int) -> float:
    """Adjust a p-value for n_trials independent looks. Data-mining haircut."""
    return min(1.0, pvalue * max(n_trials, 1))


def dataset_fingerprint(symbols: list[str], first: datetime, last: datetime, n_rows: int) -> str:
    """Stable short hash identifying the dataset a run used (reproducibility)."""
    key = f"{sorted(symbols)}|{first.isoformat()}|{last.isoformat()}|{n_rows}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]
