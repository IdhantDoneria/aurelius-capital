"""Exposure management — project target weights onto the desk's exposure budget.

Optimizers and sizers do not know a mandate's limits; this is the overlay that
enforces them before anything reaches the risk engine. Runs after sizing.

Controls & math (weights are fractions of NAV, signed):
  asset cap:       |w_i| <= max_asset_weight               (clip each name)
  sector cap:      sum_{i in k} |w_i| <= max_sector_weight (scale the sector down)
  gross leverage:  sum_i |w_i| <= max_gross_leverage       (scale the whole book)
  correlation:     if avg pairwise |rho| >= threshold, haircut gross leverage —
                   correlated names double-count risk, so an undiversified book
                   should run smaller. deleverage factor = (1 - avg_rho) clipped.

These are ordered: clip assets, scale sectors, then a single gross/correlation
scale last so the final book satisfies all three simultaneously.

Assumptions:
  - Caps are on |w| (gross), so a long and an equal short in one sector net to a
    large gross even though net is ~0 — deliberately conservative.
  - The correlation haircut uses a single average rho as a crude diversification
    proxy; it is a scalar knob, not a per-name risk model.

Limitations / when it fails:
  - Scaling a sector down uniformly preserves *relative* alpha within the sector
    but can push the book away from the optimizer's variance-optimal point.
  - Averaging rho hides structure: two tight clusters vs. uniform correlation
    look identical to this overlay. Use the risk monitor's full matrix for detail.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExposureLimits:
    max_asset_weight: float = 0.10      # |w_i| per name
    max_sector_weight: float = 0.30     # sum |w_i| per sector
    max_gross_leverage: float = 1.0     # sum |w_i| whole book
    correlation_threshold: float = 0.7  # above this avg rho, start deleveraging


def apply_limits(
    weights: dict[str, float],
    limits: ExposureLimits,
    sector_map: dict[str, str] | None = None,
    avg_correlation: float = 0.0,
) -> dict[str, float]:
    """Return weights projected into the exposure budget."""
    lim = limits
    w = {s: max(-lim.max_asset_weight, min(lim.max_asset_weight, wi))
         for s, wi in weights.items()}

    # Sector caps: scale each breaching sector's names by cap/current.
    if sector_map:
        gross_by_sector: dict[str, float] = {}
        for s, wi in w.items():
            sec = sector_map.get(s, "UNKNOWN")
            gross_by_sector[sec] = gross_by_sector.get(sec, 0.0) + abs(wi)
        for s in list(w):
            sec = sector_map.get(s, "UNKNOWN")
            g = gross_by_sector[sec]
            if g > lim.max_sector_weight:
                w[s] *= lim.max_sector_weight / g

    # Gross leverage + correlation haircut: one final scalar.
    budget = lim.max_gross_leverage
    if avg_correlation >= lim.correlation_threshold:
        budget *= max(0.0, 1.0 - avg_correlation)   # correlated book -> smaller
    gross = sum(abs(wi) for wi in w.values())
    if gross > budget and gross > 0:
        w = {s: wi * budget / gross for s, wi in w.items()}
    return w
