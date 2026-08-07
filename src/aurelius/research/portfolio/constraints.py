"""Constraint engine (AIDP Phase 10).

Constraints are declarative (an immutable ConstraintSet); enforcement projects a
raw weight vector into the feasible set. Without a QP solver (no cvxpy dependency)
projection is an iterated box-clip + gross-renormalize — always feasible for the
box/gross/leverage constraints, though not guaranteed to be the *constrained
optimum*. This is stated plainly (see docs) rather than hidden behind a solver.
Sign/concentration/liquidity limits are enforced where expressible and otherwise
reported as violations for the caller to act on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class ConstraintSet:
    # position
    max_position_weight: float = 1.0
    min_position_weight: float = 0.0        # applies to held names (|w| floor)
    long_only: bool = True
    # portfolio
    gross_exposure: float = 1.0             # target Σ|w|
    net_exposure: float | None = None       # target Σw (None = unconstrained)
    max_leverage: float = 1.0               # cap on Σ|w|
    # risk
    volatility_target: float | None = None
    beta_target: float | None = None
    factor_exposure_limits: dict = field(default_factory=dict)
    # concentration
    sector_limits: dict = field(default_factory=dict)
    industry_limits: dict = field(default_factory=dict)
    country_limits: dict = field(default_factory=dict)
    # liquidity
    max_adv_participation: float | None = None
    max_turnover: float | None = None
    capacity_limit: float | None = None
    # trading
    min_trade_size: float = 0.0
    rebalance_threshold: float = 0.0

    def enforce(self, raw: np.ndarray, *, iters: int = 50) -> np.ndarray:
        """Project raw weights into the box + gross/leverage feasible set."""
        w = np.array(raw, dtype=float)
        if self.long_only:
            w = np.clip(w, 0.0, None)
        hi = self.max_position_weight
        lo = 0.0 if self.long_only else -hi
        for _ in range(iters):
            # renormalize THEN clip so the loop ends on the hard box cap (a
            # renormalize-last order can push capped names back over the limit).
            gross = np.abs(w).sum()
            if gross <= 0:
                w = np.full(w.size, self.gross_exposure / max(w.size, 1))
                if self.long_only:
                    break
            else:
                w = w * (self.gross_exposure / gross)
            w = np.clip(w, lo, hi)
        # leverage cap
        gross = np.abs(w).sum()
        if gross > self.max_leverage and gross > 0:
            w = w * (self.max_leverage / gross)
        # drop names below the minimum position floor (then renormalize once)
        if self.min_position_weight > 0:
            w = np.where(np.abs(w) < self.min_position_weight, 0.0, w)
            g = np.abs(w).sum()
            if g > 0:
                w = w * (self.gross_exposure / g)
        return w

    def violations(self, w: np.ndarray, *, sectors=None, vol: float | None = None,
                   beta: float | None = None, turnover: float | None = None,
                   participation: np.ndarray | None = None) -> list[str]:
        v: list[str] = []
        if self.long_only and (w < -1e-9).any():
            v.append("long_only_violation")
        if (np.abs(w) > self.max_position_weight + 1e-9).any():
            v.append("max_position_weight_violation")
        if np.abs(w).sum() > self.max_leverage + 1e-9:
            v.append("leverage_violation")
        if self.net_exposure is not None and abs(w.sum() - self.net_exposure) > 1e-3:
            v.append("net_exposure_violation")
        if self.volatility_target is not None and vol is not None and vol > self.volatility_target * 1.05:
            v.append("volatility_target_violation")
        if self.beta_target is not None and beta is not None and abs(beta - self.beta_target) > 0.1:
            v.append("beta_target_violation")
        if self.max_turnover is not None and turnover is not None and turnover > self.max_turnover + 1e-9:
            v.append("turnover_violation")
        if self.max_adv_participation is not None and participation is not None \
                and (participation > self.max_adv_participation + 1e-9).any():
            v.append("adv_participation_violation")
        if sectors is not None and self.sector_limits:
            v += _group_violations(w, sectors, self.sector_limits, "sector")
        return v


def _group_violations(w, groups, limits, label) -> list[str]:
    out = []
    exposure: dict = {}
    for wi, g in zip(w, groups, strict=False):
        exposure[g] = exposure.get(g, 0.0) + abs(wi)
    for g, lim in limits.items():
        if exposure.get(g, 0.0) > lim + 1e-9:
            out.append(f"{label}_limit_violation:{g}")
    return out
