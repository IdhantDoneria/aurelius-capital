"""Technical indicators: RSI, MACD histogram, Bollinger %B."""

from __future__ import annotations

import statistics
from decimal import Decimal

from aurelius.features.registry import (
    Category,
    ValidationStatus,
    Window,
    ema,
    feature,
)

_OWNER = "quant-core"


@feature(
    name="rsi_14",
    category=Category.TECHNICAL,
    description="14-bar Relative Strength Index (simple-average variant).",
    formula="100 - 100/(1 + avg_gain/avg_loss) over last 14 returns",
    inputs=("close",),
    min_periods=15,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="Momentum oscillator; extremes flag over-extension of buyers/sellers.",
    expected_behavior="Bounded [0,100]; >70 overbought, <30 oversold, mean-reverting.",
    failure_modes="Stays pinned >70 in strong uptrends (not a sell); SMA (not Wilder) smoothing.",
    validation_method="All-up window → 100; all-down → 0; bounded within [0,100].",
)
def rsi_14(w: Window) -> Decimal | None:
    if len(w.close) < 15:
        return None
    diffs = [w.close[i] - w.close[i - 1] for i in range(len(w.close) - 14, len(w.close))]
    gains = [float(d) for d in diffs if d > 0]
    losses = [-float(d) for d in diffs if d < 0]
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    if avg_loss == 0:
        return Decimal(100) if avg_gain > 0 else Decimal(50)
    rs = avg_gain / avg_loss
    return Decimal(str(100 - 100 / (1 + rs)))


@feature(
    name="macd_hist",
    category=Category.TECHNICAL,
    description="MACD histogram: (EMA12 - EMA26) minus its 9-bar signal EMA.",
    formula="macd = EMA12 - EMA26; signal = EMA9(macd); hist = macd - signal",
    inputs=("close",),
    min_periods=35,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="Trend-following momentum; histogram leads MACD/signal crossovers.",
    expected_behavior="Crosses 0 as momentum flips; magnitude tracks trend acceleration.",
    failure_modes="Lagging; false flips in chop. Signal EMA here is seeded on the MACD series.",
    validation_method="Steady uptrend → positive histogram; sign flips after a sustained reversal.",
)
def macd_hist(w: Window) -> Decimal | None:
    if len(w.close) < 35:
        return None
    # Build the MACD line series so its 9-bar signal EMA has history to smooth.
    macd_series: list[Decimal] = []
    for i in range(26, len(w.close) + 1):
        e12 = ema(w.close[:i], 12)
        e26 = ema(w.close[:i], 26)
        if e12 is None or e26 is None:
            return None
        macd_series.append(Decimal(str(e12 - e26)))
    if len(macd_series) < 9:
        return None
    signal = ema(macd_series, 9)
    if signal is None:
        return None
    return macd_series[-1] - Decimal(str(signal))


@feature(
    name="bollinger_pctb_20",
    category=Category.TECHNICAL,
    description="Bollinger %B: close position within 20-bar, 2sigma bands.",
    formula="(close - lower) / (upper - lower), bands = mean ± 2·stdev(close[-20:])",
    inputs=("close",),
    min_periods=20,
    owner=_OWNER,
    status=ValidationStatus.VALIDATED,
    economic_intuition="Where price sits in its recent range, normalized by volatility.",
    expected_behavior="0 at lower band, 1 at upper, 0.5 at mean; <0 or >1 on band breaks.",
    failure_modes="Undefined when volatility is 0 (flat window); trends ride the upper band.",
    validation_method="Close at mean -> 0.5; close at mean+2sigma -> 1.0.",
)
def bollinger_pctb_20(w: Window) -> Decimal | None:
    if len(w.close) < 20:
        return None
    vals = [float(c) for c in w.close[-20:]]
    m = statistics.mean(vals)
    sd = statistics.stdev(vals)
    if sd == 0:
        return None
    lower, upper = m - 2 * sd, m + 2 * sd
    return Decimal(str((vals[-1] - lower) / (upper - lower)))
