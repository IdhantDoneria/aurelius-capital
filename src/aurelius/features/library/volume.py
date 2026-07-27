"""Volume features."""

from __future__ import annotations

import statistics
from decimal import Decimal

from aurelius.features.registry import (
    Category,
    ValidationStatus,
    Window,
    feature,
    pct_change,
)

_OWNER = "quant-core"


@feature(
    name="volume_change_1d",
    category=Category.VOLUME,
    description="1-day change in volume.",
    formula="(vol_t - vol_{t-1}) / vol_{t-1}",
    inputs=("volume",),
    min_periods=2,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="A jump in participation often precedes or confirms a price move.",
    expected_behavior="Spiky and mean-reverting; large positive values cluster around news.",
    failure_modes="Prev volume of 0 (halts/holidays) → undefined; noisy for thin names.",
    validation_method="Doubling of volume → +1.0.",
)
def volume_change_1d(w: Window) -> Decimal | None:
    return pct_change(w.volume, 1)


@feature(
    name="relative_volume_20",
    category=Category.VOLUME,
    description="Today's volume relative to its 20-bar average.",
    formula="vol_t / mean(vol[-20:])",
    inputs=("volume",),
    min_periods=20,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="Normalizes participation to the symbol's own baseline (RVOL).",
    expected_behavior="~1 on quiet days; >2 on breakouts, earnings, index events.",
    failure_modes="Average of 0 → undefined; drifts after a permanent liquidity regime change.",
    validation_method="Volume equal to its trailing mean → 1.0.",
)
def relative_volume_20(w: Window) -> Decimal | None:
    if len(w.volume) < 20:
        return None
    avg = sum(w.volume[-20:]) / Decimal(20)
    if avg == 0:
        return None
    return w.volume[-1] / avg


@feature(
    name="volume_anomaly_20",
    category=Category.VOLUME,
    description="Z-score of today's volume vs its trailing 20-bar distribution.",
    formula="(vol_t - mean(vol[-20:])) / stdev(vol[-20:])",
    inputs=("volume",),
    min_periods=20,
    owner=_OWNER,
    status=ValidationStatus.EXPERIMENTAL,
    economic_intuition=(
        "Statistically unusual participation flags informed trading / regime shifts."
    ),
    expected_behavior="Near 0 normally; large positive spikes on abnormal activity.",
    failure_modes="Right-skewed volume breaks the normality assumption; flat window → undefined.",
    validation_method="A single large spike over a flat history → large positive z.",
)
def volume_anomaly_20(w: Window) -> Decimal | None:
    if len(w.volume) < 20:
        return None
    vals = [float(v) for v in w.volume[-20:]]
    sd = statistics.stdev(vals)
    if sd == 0:
        return Decimal(0)
    return Decimal(str((vals[-1] - statistics.mean(vals)) / sd))
