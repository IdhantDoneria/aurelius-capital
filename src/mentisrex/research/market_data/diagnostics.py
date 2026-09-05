"""Market-data quality diagnostics (AIDP M19).

Pure, deterministic checks over raw/canonical market data. Each returns a message string on a
problem, or None when clean — the quality engine composes them into severity-tagged
`QualityDiagnostic`s. M18's arbitrage diagnostics (curve DF positivity, FX reciprocal,
vol calendar-spread) are reused directly rather than re-implemented; this module adds the
market-microstructure and data-integrity checks M18 did not cover.
"""

from __future__ import annotations

# re-export the M18 arbitrage diagnostics so callers have one import surface
from mentisrex.research.valuation.diagnostics import (  # noqa: F401
    calendar_spread,
    curve_discontinuities,
    fx_reciprocal,
    negative_discount_factors,
    option_bounds,
    put_call_parity,
)


def bad_ohlc(o: float, h: float, l: float, c: float) -> str | None:
    """Open/high/low/close must satisfy low <= {open,close} <= high and high >= low."""
    if h < l:
        return f"high {h} < low {l}"
    for name, v in (("open", o), ("close", c)):
        if v < l - 1e-12 or v > h + 1e-12:
            return f"{name} {v} outside [low {l}, high {h}]"
    return None


def crossed_quote(bid: float, ask: float) -> str | None:
    if bid is None or ask is None:
        return None
    if bid > ask + 1e-12:
        return f"crossed market: bid {bid} > ask {ask}"
    return None


def wide_spread(bid: float, ask: float, *, max_frac: float = 0.10) -> str | None:
    if bid is None or ask is None or bid <= 0:
        return None
    mid = 0.5 * (bid + ask)
    if mid > 0 and (ask - bid) / mid > max_frac:
        return f"wide spread {(ask - bid) / mid:.3f} > {max_frac}"
    return None


def price_jump(prev: float, curr: float, *, max_frac: float = 0.5) -> str | None:
    if prev is None or curr is None or prev <= 0:
        return None
    if abs(curr - prev) / prev > max_frac:
        return f"price jump {(curr - prev) / prev:+.3f} > {max_frac}"
    return None


def non_positive_price(value: float) -> str | None:
    return f"non-positive price {value}" if value is not None and value <= 0 else None


def negative_volume(value: float) -> str | None:
    return f"negative volume {value}" if value is not None and value < 0 else None


def negative_variance(vol: float, t: float) -> str | None:
    if vol is None or t is None:
        return None
    if vol < 0:
        return f"negative implied vol {vol}"
    if vol * vol * t < 0:
        return f"negative total variance at t={t}"
    return None


def stale(observation_date, as_of, max_days: int | None) -> str | None:
    if max_days is None or observation_date is None or as_of is None:
        return None
    age = (as_of - observation_date).days
    return f"stale by {age}d (> {max_days}d)" if age > max_days else None


def look_ahead(observation_date, as_of) -> str | None:
    if observation_date is None or as_of is None:
        return None
    return (
        f"look-ahead: observed {observation_date} after valuation {as_of}"
        if observation_date > as_of
        else None
    )
