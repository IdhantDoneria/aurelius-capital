"""Generic liquidity-metric registry for the M7 investable-universe screen.

M6 approved exactly one methodology improvement: a liquidity screen built from
information already in the panel (close + volume only — no market cap, no shares
outstanding, no exchange, no look-ahead). This module is that screen's metric
library. It is deliberately generic: a name→(fn, higher_is_more_liquid) registry
so the strategy can screen on ANY approved metric, not a hard-coded Amihud.

Each metric maps a trailing window of (closes, volumes) — all bars <= t, so no
look-ahead — to a scalar. `higher_is_more_liquid` tells the screen which tail to
drop (dollar volume / ADV: drop the low tail; Amihud illiquidity: drop the high
tail).

The FactorStrategy screen applies these RELATIVELY: at each rebalance it drops the
bottom `liquidity_pct` fraction of the cross-section by liquidity. Relative (not an
absolute currency floor) because the panel mixes US ($) and India (₹) names ~80×
apart in nominal dollar volume — a single absolute threshold would delete one
market. A cross-sectional percentile cut is self-calibrating per rebalance and
market-neutral.

DEFAULT = median dollar volume, selected on M6's four criteria:
  * scientific defensibility — standard institutional liquidity proxy, Amihud (2002)
    lineage; measures exactly what it claims (traded value).
  * stability — median is robust to the volume spikes that whipsaw a mean.
  * data availability — needs only close + volume, both fully populated (vwap and
    trade_count are 100% NULL in this panel; ADV alone ignores price level).
  * computational efficiency — O(W log W) per name, W≈21; no division (Amihud's
    1/dollar-volume blows up on the panel's 3% zero-volume bars).
"""

from __future__ import annotations

import statistics


def _dollar(closes: list[float], volumes: list[float]) -> list[float]:
    return [c * v for c, v in zip(closes, volumes, strict=False)]


def dollar_volume_median(closes: list[float], volumes: list[float]) -> float:
    """Median daily close×volume over the window. Default metric."""
    return statistics.median(_dollar(closes, volumes))


def dollar_volume_mean(closes: list[float], volumes: list[float]) -> float:
    """Mean daily close×volume over the window."""
    dv = _dollar(closes, volumes)
    return sum(dv) / len(dv)


def adv(closes: list[float], volumes: list[float]) -> float:
    """Average daily (share) volume over the window."""
    return sum(volumes) / len(volumes)


def amihud(closes: list[float], volumes: list[float]) -> float:
    """Amihud (2002) illiquidity: mean |return| / dollar volume. Higher = LESS
    liquid. Zero-volume bars are skipped (division guard)."""
    ills: list[float] = []
    for i in range(1, len(closes)):
        dv = closes[i] * volumes[i]
        if dv <= 0 or closes[i - 1] == 0:
            continue
        ills.append(abs(closes[i] - closes[i - 1]) / closes[i - 1] / dv)
    return sum(ills) / len(ills) if ills else float("inf")


# name -> (metric_fn, higher_is_more_liquid)
LIQUIDITY_METRICS: dict[str, tuple] = {
    "dollar_volume_median": (dollar_volume_median, True),
    "dollar_volume_mean": (dollar_volume_mean, True),
    "adv": (adv, True),
    "amihud": (amihud, False),
}

DEFAULT_METRIC = "dollar_volume_median"


def screen(liq: dict[str, float], pct: float, higher_is_more_liquid: bool) -> set[str]:
    """Return the survivors: names to KEEP after dropping the bottom `pct`
    fraction by liquidity. Look-ahead-free (caller passes only trailing-window
    metrics). pct<=0 -> keep everything (screen disabled)."""
    n = len(liq)
    n_drop = int(pct * n)
    if n_drop <= 0:
        return set(liq)
    # most-liquid first, then keep all but the n_drop least liquid
    ordered = sorted(liq, key=lambda s: liq[s], reverse=higher_is_more_liquid)
    return set(ordered[: n - n_drop])


if __name__ == "__main__":
    # self-check: registry wired, screen drops the right tail for both directions
    cl = [10.0] * 5
    vols = {"A": 100, "B": 200, "C": 300, "D": 400, "E": 500}
    liq = {s: dollar_volume_mean(cl, [v] * 5) for s, v in vols.items()}
    surv = screen(liq, 0.4, True)  # drop bottom 2 by $vol -> A,B gone
    assert surv == {"C", "D", "E"}, surv
    # amihud: higher = less liquid -> dropping bottom 40% removes the 2 LEAST liquid
    ill = {"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0}  # A,B most illiquid
    surv2 = screen(ill, 0.4, False)
    assert surv2 == {"C", "D", "E"}, surv2
    # disabled
    assert screen(liq, 0.0, True) == set(liq)
    print("liquidity self-check OK")
