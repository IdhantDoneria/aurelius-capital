"""The ten signals: mechanism, estimator, source paper for each.

This module has one job: turn a `PricePanel` into raw scores. Directional
sleeves (S1-S4) return a `pd.Series` of benchmark exposure in [0, 1].
Cross-sectional sleeves (S5-S10) return a `pd.DataFrame` of raw z-scores over
`panel.universe_columns()`, NaN where ineligible. Converting cross-sectional
scores into dollar-neutral portfolio weights (demean, scale to gross 1.0) is
`sleeves.py`'s job, not this module's -- every function here stops at the raw
score.

No look-ahead, anywhere: for row `t`, every function here uses only panel data
at or before `t`. Every rolling window is trailing; `s4_panic_reversal`'s
single forward pass over the date index only ever reads state carried forward
from earlier dates. `test_no_lookahead_signals` truncates the panel and
requires retained values to be bit-identical.

Numeric core is float64 pandas/numpy throughout, per house convention (money
is only ever `Decimal` at the broker boundary in `execution.py`).

Source of truth for the estimators and the economic story behind each one:
`US Equity Systematic Programme v3.0 Full Specification`, section 3
(mechanism/estimator/evidence per sleeve) and section 11.3 (parameter
sensitivity -- Table 18 shows the production parameter set sits at the median
of 51 whole-book backtests across twelve parameters, not the maximum, which is
the strongest evidence in the spec against these being fitted values).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from mentisrex.programme.config import SignalConfig
    from mentisrex.programme.data import PricePanel

# Fixed liquidity-screen window for S10's liquid-half restriction, spec 3.3.
# Not exposed in SignalConfig -- it is the same 21-day dollar-volume window
# used everywhere else in the programme for "how liquid is this name right
# now" (cf. UniverseConfig.min_dollar_volume's own 21-day median), not an
# independently tuned parameter of the reversal sleeve.
_S10_LIQUIDITY_WINDOW = 21


def cross_sectional_zscore(frame: pd.DataFrame, mask: pd.DataFrame) -> pd.DataFrame:
    """Shared cross-sectional standardiser used by every S5-S10 signal.

    Per date (row): mask to eligible names, winsorise at +/-5 raw MAD-sigmas
    (median absolute deviation, not scaled by the 1.4826 normal-consistency
    factor -- "raw" MAD-sigmas), then z-score over the non-null entries. Rows
    with fewer than 20 valid names become all-NaN -- there is no meaningful
    cross-section to standardise against with that few names.

    Purely cross-sectional (row-by-row): does not touch any other date, so it
    cannot introduce look-ahead on its own -- that property is inherited from
    whatever trailing-window `frame` it is given.

    Guards division by zero and a zero cross-sectional std by producing NaN,
    never inf: a row where every eligible value is identical has MAD == 0 and
    std == 0 after winsorising, and z-scoring a constant is undefined.
    """
    eligible = frame.where(mask)
    n_valid = eligible.notna().sum(axis=1)

    median = eligible.median(axis=1)
    mad = eligible.sub(median, axis=0).abs().median(axis=1)
    bound = 5.0 * mad
    winsorised = eligible.clip(lower=median - bound, upper=median + bound, axis=0)

    row_mean = winsorised.mean(axis=1)
    row_std = winsorised.std(axis=1)
    row_std_safe = row_std.where(row_std > 0)

    z = winsorised.sub(row_mean, axis=0).div(row_std_safe, axis=0)
    z.loc[n_valid < 20, :] = np.nan
    return z


def _formation_raw_return(panel: PricePanel, config: SignalConfig) -> pd.DataFrame:
    """Raw (unscored) 12-1-style formation-window return, shared by S5/S6/S7.

    cum return from t-momentum_lookback to t-momentum_skip:
    close.shift(momentum_skip) / close.shift(momentum_lookback) - 1. The skip
    gap excludes the most recent `momentum_skip` days, the standard device to
    avoid the short-horizon reversal effect (S10's territory) contaminating
    the momentum estimate.
    """
    close = panel.close[panel.universe_columns()]
    return close.shift(config.momentum_skip) / close.shift(config.momentum_lookback) - 1.0


def s1_trend(panel: PricePanel, config: SignalConfig) -> pd.Series:
    """S1 -- multi-horizon time-series trend (Moskowitz, Ooi & Pedersen 2012).

    Mechanism. An asset's own past return predicts its own future return over
    one to twelve months. The economic content is slow information diffusion
    combined with under-reaction: institutional rebalancing, risk-management
    selling and capital flows take weeks to complete, so a price move that
    begins today is still being pushed tomorrow.

    Estimator. Mean of seven binary indicators on the benchmark: close above
    its 50-, 100-, 150- and 200-day moving average, and positive 63-, 126- and
    252-day cumulative return. Clipped to [0, 1] -- long or flat, never short.
    Averaging seven lookbacks rather than selecting one is the robustness
    decision: any individual rule is a fitted parameter, the mean of seven is
    close to parameter-free.

    Why it survives. Trend-following is uncomfortable to hold (it whipsaws in
    ranging markets, lags V-shaped recoveries), and discomfort is why it is
    not arbitraged away.

    Note: before a window's history exists (e.g. the first 200 days for the
    200-day MA), `close > ma` compares against NaN, which pandas evaluates as
    False rather than NaN. Early-history exposure is therefore biased toward
    the "not trending" side of each indicator rather than undefined -- a
    conservative, non-look-ahead warm-up artifact, not a leak.
    """
    close = panel.benchmark_close
    indicators = [(close > close.rolling(w).mean()).astype(float) for w in config.trend_ma_windows]
    indicators += [(close > close.shift(w)).astype(float) for w in config.trend_return_windows]
    exposure = pd.concat(indicators, axis=1).mean(axis=1)
    return exposure.clip(0.0, 1.0)


def s2_vol_managed(panel: PricePanel, config: SignalConfig) -> pd.Series:
    """S2 -- volatility-managed market exposure (Moreira & Muir 2017).

    Mechanism. Volatility is far more forecastable than return, so scaling
    exposure inversely to trailing volatility raises risk-adjusted return
    without requiring any view on direction.

    Estimator. exposure = clip(vol_target / RV63, floor, cap), where RV63 is
    63-day trailing realised volatility of benchmark daily returns, annualised
    by sqrt(252).

    Why it is retained despite contrary evidence. Cederburg, O'Doherty, Wang
    and Yan (2020) find volatility management adds no out-of-sample value on
    the market factor alone. Accepted -- S2 is kept for the automatic
    de-levering it supplies under stress, not for expected alpha; it is a risk
    control expressed as a sleeve.

    CONTRACT: this returns the raw clipped exposure in [floor, cap], e.g.
    [0.4, 1.8] at defaults -- NOT rescaled to [0, 1]. The allocator averages
    raw directional exposures across S1-S4 (spec sec 4.2); rescaling here
    would silently change that average.
    """
    ret = panel.benchmark_returns
    rv = ret.rolling(config.vol_window).std() * np.sqrt(252)
    rv_safe = rv.where(rv > 0)
    exposure = (config.vol_target / rv_safe).clip(
        config.vol_exposure_floor, config.vol_exposure_cap
    )
    return exposure


def s3_breadth(panel: PricePanel, mask: pd.DataFrame, config: SignalConfig) -> pd.Series:
    """S3 -- cross-sectional breadth timing.

    Mechanism. Participation. An index advance carried by a narrowing set of
    names is a weaker signal than the index level alone suggests, because it
    means the marginal buyer has run out of things to buy.

    Estimator. b(t) = fraction of ELIGIBLE names with close above their own
    200-day moving average. Standardised against its own trailing
    `breadth_z_window`-day distribution: z = (b - rolling_mean(b)) /
    rolling_std(b). Squashed through tanh into [0, 1]: (tanh(z) + 1) / 2.

    Evidence (spec sec 8, the spec's claim). The sharpest regime split in the
    programme: in the broadest third of the sample the book returns +68.9%
    annualised; in the narrowest third, -6.6%. S3 is what makes the book pay
    attention to that.
    """
    close = panel.close[panel.universe_columns()]
    ma = close.rolling(config.breadth_ma_window).mean()
    above_eligible = (close > ma) & mask

    n_eligible = mask.sum(axis=1)
    n_eligible_safe = n_eligible.where(n_eligible > 0)
    breadth = above_eligible.sum(axis=1) / n_eligible_safe

    roll_mean = breadth.rolling(config.breadth_z_window).mean()
    roll_std = breadth.rolling(config.breadth_z_window).std()
    roll_std_safe = roll_std.where(roll_std > 0)
    z = (breadth - roll_mean) / roll_std_safe

    return (np.tanh(z) + 1.0) / 2.0


def s4_panic_reversal(panel: PricePanel, config: SignalConfig) -> pd.Series:
    """S4 -- volatility term-structure panic reversal (Nagel 2012).

    Mechanism. Liquidity provision. When short-horizon realised volatility
    spikes above medium-horizon volatility and the index has fallen, the
    market is paying an unusually high price for immediacy; supplying it is
    compensated.

    Estimator. ratio = RV(panic_fast_window) / RV(panic_slow_window) of
    benchmark daily returns (the annualisation constant cancels in the ratio,
    so raw rolling std is used for both). Triggers when ratio exceeds
    `panic_trigger_ratio` AND the trailing `panic_return_window`-day benchmark
    return is below `panic_return_threshold`. Size on trigger =
    clip(ratio - panic_trigger_ratio, 0, 1).

    The one genuinely stateful signal (causal single forward pass over dates,
    O(dates)). Position decays linearly to zero over `panic_max_hold_days`
    after a trigger (full size on the trigger day itself, zero by day
    `panic_max_hold_days`). A new trigger while a previous one is still
    decaying resets the hold clock and takes max(currently-decayed level, new
    trigger size) as the new base -- it never downgrades an already-larger
    position.

    Regime gate: forced to zero whenever benchmark close is more than 15%
    (`panic_regime_drawdown`) below its `panic_regime_ma_window`-day average.
    Applied as a final elementwise override on the exposure path rather than
    resetting the internal decay state -- a day the gate suppresses does not
    erase the memory of the trigger that produced it; if the regime clears
    before the hold period expires, the decay resumes where it would have
    been had the gate never fired.

    Honest assessment (spec 3.3, the spec's claim). The weakest sleeve in the
    core, t = 1.45. Retained because it is the only core sleeve not highly
    correlated with S1-S3 -- it is a diversifier, sized as one.
    """
    ret = panel.benchmark_returns
    close = panel.benchmark_close

    rv_fast = ret.rolling(config.panic_fast_window).std()
    rv_slow = ret.rolling(config.panic_slow_window).std()
    rv_slow_safe = rv_slow.where(rv_slow > 0)
    ratio = rv_fast / rv_slow_safe

    window_return = close.pct_change(config.panic_return_window)
    trigger = (ratio > config.panic_trigger_ratio) & (window_return < config.panic_return_threshold)
    trigger = trigger.fillna(False)
    size = (ratio - config.panic_trigger_ratio).clip(lower=0.0, upper=1.0)

    max_hold = config.panic_max_hold_days
    levels: list[float] = []
    s0 = 0.0
    age = 0
    for trig, sz in zip(trigger.to_numpy(), size.to_numpy(), strict=True):
        decayed = s0 * max(0.0, 1.0 - age / max_hold) if s0 > 0.0 else 0.0
        if trig:
            new_size = 0.0 if np.isnan(sz) else float(sz)
            s0 = max(decayed, new_size)
            age = 0
            level = s0
        else:
            level = decayed
        levels.append(level)
        age += 1

    exposure = pd.Series(levels, index=ret.index, dtype=float)

    regime_ma = close.rolling(config.panic_regime_ma_window).mean()
    regime_breach = (close < (1.0 + config.panic_regime_drawdown) * regime_ma).fillna(False)
    exposure = exposure.where(~regime_breach, 0.0)

    return exposure.clip(0.0, 1.0)


def s5_momentum(panel: PricePanel, mask: pd.DataFrame, config: SignalConfig) -> pd.DataFrame:
    """S5 -- cross-sectional 12-1 momentum (Jegadeesh & Titman 1993).

    Mechanism. Under-reaction to gradually-diffusing information plus delayed
    institutional repositioning -- the raw member of the momentum family (see
    also S6, S7, which strip out beta exposure and amplify by information
    discreteness respectively).

    Estimator. Cumulative return from t-momentum_lookback to t-momentum_skip:
    close.shift(momentum_skip) / close.shift(momentum_lookback) - 1,
    cross-sectionally z-scored over eligible names each date.
    """
    raw = _formation_raw_return(panel, config)
    return cross_sectional_zscore(raw, mask)


def s6_residual_momentum(
    panel: PricePanel, mask: pd.DataFrame, config: SignalConfig
) -> pd.DataFrame:
    """S6 -- residual (beta-adjusted) momentum (Blitz, Huij & Martens 2011).

    Mechanism. Same under-reaction as S5, but computed on market-model
    residuals, which removes the beta exposure responsible for momentum
    crashes: after a bear market the raw-momentum short leg is loaded with
    high-beta names that rip in the rebound, and the residual version does not
    carry that.

    Estimator. Rolling `residual_beta_window`-day market-model beta of each
    name's daily return on the benchmark return, computed via rolling
    covariance / rolling variance across the whole frame at once (vectorised:
    cov and var are each built from `.rolling(w).mean()` calls on the full
    frame, never a per-name regression loop). Residual_i(t) = r_i(t) -
    beta_i(t) * r_bm(t). Residual momentum = sum of residuals over the
    t-momentum_lookback .. t-momentum_skip formation window, divided by the
    residual standard deviation over the same window (an information ratio),
    cross-sectionally z-scored.
    """
    returns = panel.returns[panel.universe_columns()]
    bm_returns = panel.benchmark_returns
    w = config.residual_beta_window

    mean_i = returns.rolling(w).mean()
    mean_bm = bm_returns.rolling(w).mean()
    mean_i_bm = returns.mul(bm_returns, axis=0).rolling(w).mean()
    cov = mean_i_bm - mean_i.mul(mean_bm, axis=0)

    var_bm = (bm_returns**2).rolling(w).mean() - mean_bm**2
    var_bm_safe = var_bm.where(var_bm > 0)

    beta = cov.div(var_bm_safe, axis=0)
    residual = returns - beta.mul(bm_returns, axis=0)

    window_len = config.momentum_lookback - config.momentum_skip
    resid_sum = residual.rolling(window_len).sum().shift(config.momentum_skip)
    resid_std = residual.rolling(window_len).std().shift(config.momentum_skip)
    resid_std_safe = resid_std.where(resid_std > 0)

    raw = resid_sum / resid_std_safe
    return cross_sectional_zscore(raw, mask)


def s7_id_momentum(panel: PricePanel, mask: pd.DataFrame, config: SignalConfig) -> pd.DataFrame:
    """S7 -- information-discreteness momentum (Da, Gurun & Warachka 2014).

    Mechanism. A price move delivered by many small daily increments diffuses
    more slowly, and attracts less attention, than the same total move
    delivered by a few large jumps -- "frog in the pan". Amplifies S5's
    momentum by how discretely the formation-window move arrived.

    Estimator. z5 = S5's cross-sectional z-score. Over the formation window
    (t-momentum_lookback .. t-momentum_skip): pct_neg / pct_pos = fraction of
    days with a negative / positive raw return; ID = sign(raw momentum) *
    (pct_neg - pct_pos); zid = cross-sectional z-score of ID. result = z5 * (1
    + id_weight * clip(-zid, -id_clip, id_clip)), cross-sectionally
    re-z-scored.
    """
    raw_momentum = _formation_raw_return(panel, config)
    z5 = cross_sectional_zscore(raw_momentum, mask)

    returns = panel.returns[panel.universe_columns()]
    window_len = config.momentum_lookback - config.momentum_skip
    pct_neg = (returns < 0).rolling(window_len).mean().shift(config.momentum_skip)
    pct_pos = (returns > 0).rolling(window_len).mean().shift(config.momentum_skip)

    information_discreteness = np.sign(raw_momentum) * (pct_neg - pct_pos)
    zid = cross_sectional_zscore(information_discreteness, mask)

    adjustment = 1.0 + config.id_weight * (-zid).clip(-config.id_clip, config.id_clip)
    result = z5 * adjustment
    return cross_sectional_zscore(result, mask)


def s8_illiquidity(panel: PricePanel, mask: pd.DataFrame, config: SignalConfig) -> pd.DataFrame:
    """S8 -- Amihud illiquidity premium (Amihud 2002).

    Mechanism. Compensation for bearing liquidity risk: investors demand a
    premium for holding securities that are expensive to exit. Structurally
    available here and not to a large manager -- a fund running billions
    cannot hold the illiquid tail in size, a small book can.

    Estimator. `amihud_window`-day rolling mean of |return| / dollar_volume,
    z-scored. Positive z = illiquid = LONG.

    # CONTRACT-NOTE: the raw Amihud ratio has an extreme right tail (a single
    # thinly-traded name on a big-move day dwarfs everything else), so it is
    # log1p-transformed before z-scoring to tame that tail. This transform is
    # an implementation choice, not something the spec states.
    """
    returns = panel.returns[panel.universe_columns()]
    dollar_volume = panel.dollar_volume[panel.universe_columns()]
    dollar_volume_safe = dollar_volume.where(dollar_volume > 0)

    daily_amihud = returns.abs() / dollar_volume_safe
    amihud = daily_amihud.rolling(config.amihud_window).mean()
    transformed = np.log1p(amihud)
    return cross_sectional_zscore(transformed, mask)


def s9_relative_volume(panel: PricePanel, mask: pd.DataFrame, config: SignalConfig) -> pd.DataFrame:
    """S9 -- relative-volume attention.

    Mechanism. Volume proxies for investor attention, and attention precedes
    flow.

    Estimator. `relvol_fast_window`-day rolling mean dollar volume divided by
    `relvol_slow_window`-day rolling mean dollar volume, z-scored.
    """
    dollar_volume = panel.dollar_volume[panel.universe_columns()]
    fast = dollar_volume.rolling(config.relvol_fast_window).mean()
    slow = dollar_volume.rolling(config.relvol_slow_window).mean()
    slow_safe = slow.where(slow > 0)
    raw = fast / slow_safe
    return cross_sectional_zscore(raw, mask)


def s10_reversal(panel: PricePanel, mask: pd.DataFrame, config: SignalConfig) -> pd.DataFrame:
    """S10 -- conditional short-horizon reversal (Nagel 2012; Novy-Marx &
    Velikov 2023).

    Mechanism. Compensation for supplying immediacy to impatient traders.

    Estimator. raw = -(close / close.shift(reversal_window) - 1) /
    (rolling_std(returns, reversal_vol_window) * sqrt(252)). Restricted to the
    liquid half of the universe: on each date, keep only names whose
    21-day median dollar volume is >= the cross-sectional quantile at
    (1 - reversal_liquid_fraction) among ELIGIBLE names -- at the default
    `reversal_liquid_fraction=0.5` this is exactly a median split; others are
    NaN. Then cross-sectionally z-scored.

    The weakest sleeve in the book (spec 3.3, the spec's claim): the raw
    signal is strong but its IC peaks at 3 days and is gone by 10, which is
    exactly the horizon at which turnover-driven cost eats it -- the clearest
    illustration in the spec of section 3.1's cost-versus-horizon inequality.
    """
    close = panel.close[panel.universe_columns()]
    returns = panel.returns[panel.universe_columns()]
    dollar_volume = panel.dollar_volume[panel.universe_columns()]

    cum_return = close / close.shift(config.reversal_window) - 1.0
    vol = returns.rolling(config.reversal_vol_window).std() * np.sqrt(252)
    vol_safe = vol.where(vol > 0)
    raw = -cum_return / vol_safe

    median_dollar_volume = dollar_volume.rolling(_S10_LIQUIDITY_WINDOW).median()
    eligible_liquidity = median_dollar_volume.where(mask)
    cutoff = eligible_liquidity.quantile(1.0 - config.reversal_liquid_fraction, axis=1)
    liquid = eligible_liquidity.ge(cutoff, axis=0)

    raw_liquid = raw.where(liquid)
    return cross_sectional_zscore(raw_liquid, mask)


SIGNAL_FUNCS: dict[str, Callable[..., pd.Series | pd.DataFrame]] = {
    "S1": s1_trend,
    "S2": s2_vol_managed,
    "S3": s3_breadth,
    "S4": s4_panic_reversal,
    "S5": s5_momentum,
    "S6": s6_residual_momentum,
    "S7": s7_id_momentum,
    "S8": s8_illiquidity,
    "S9": s9_relative_volume,
    "S10": s10_reversal,
}

# S1, S2, S4 are directional signals computed purely from the benchmark and
# take no eligibility mask; every other sleeve is cross-sectional and needs it.
_NO_MASK_SIGNALS = frozenset({"S1", "S2", "S4"})


def compute_all_signals(
    panel: PricePanel, mask: pd.DataFrame, config: SignalConfig
) -> dict[str, pd.Series | pd.DataFrame]:
    """Compute all ten signals. Pure -- no state, no I/O.

    Returns {"S1": pd.Series, ..., "S4": pd.Series, "S5": pd.DataFrame, ...,
    "S10": pd.DataFrame} keyed exactly as `SIGNAL_FUNCS`.
    """
    results: dict[str, pd.Series | pd.DataFrame] = {}
    for name, func in SIGNAL_FUNCS.items():
        if name in _NO_MASK_SIGNALS:
            results[name] = func(panel, config)
        else:
            results[name] = func(panel, mask, config)
    return results
