"""ResearchMatrix -> factor-panel adapter (M36).

Turns a time series of PIT `ResearchMatrix` snapshots into the per-date dict
panels the campaign engine (M34/M35) consumes: a signal cross-section per
rebalance date and a PIT-correct forward-return label to the next rebalance.

Duck-typed on purpose — no hard dependency on the concrete price store or
security master, so it is unit-testable with fakes and wired in production with:
  close_fn  = PitPriceStore.close_as_of        # (symbol, as_of, knowledge_date=None) -> float|None
  symbol_fn = SecurityMaster.historical_identifier  # (security_id, as_of) -> str|None

Forward return is rebalance-to-rebalance: r_i = close(t_{i+1}) / close(t_i) - 1,
both legs back-adjusted into the *endpoint* frame (knowledge_date = t_{i+1}) so a
split inside the holding window cannot distort the ratio. The signal at t_i uses
only the matrix built on t_i — no look-ahead. Names with a missing price on
either leg (e.g. delisted before t_{i+1}) are dropped from that date's label.
"""

from __future__ import annotations

from datetime import date


def _matrix_signal(matrix, feature: str, apply_direction: bool) -> dict:
    """Signal cross-section {security_id: value} from a matrix frame, NaNs dropped.
    When apply_direction, a 'lower'-is-better feature is negated so a larger
    oriented value always means a stronger long — keeps IC/long-book signs sane."""
    frame = matrix.frame
    if feature not in frame.columns:
        raise ValueError(f"feature {feature!r} not in matrix columns")
    col = frame[feature]
    sign = -1.0 if (apply_direction and matrix.directions.get(feature) == "lower") else 1.0
    out = {}
    for sid, v in col.items():
        if v is not None and v == v:  # not None, not NaN
            out[sid] = sign * float(v)
    return out


def _forward_returns(sids, t: date, t_next: date, close_fn, symbol_fn) -> dict:
    out = {}
    for sid in sids:
        sym = symbol_fn(sid, t)
        if not sym:
            continue
        c0 = close_fn(sym, t, t_next)      # entry leg, adjusted into endpoint frame
        c1 = close_fn(sym, t_next, t_next)
        if c0 and c1 and c0 != 0:
            out[sid] = c1 / c0 - 1.0
    return out


def panels_from_matrices(
    matrices: list,
    feature: str,
    *,
    close_fn,
    symbol_fn,
    apply_direction: bool = True,
) -> tuple[list[dict], list[dict]]:
    """(signals, forward_returns) aligned per rebalance, ready for evaluate_factor
    / FactorCampaign.run. Matrices are sorted by `as_of_date`; the last date has no
    forward window and is dropped. Requires >= 2 dated matrices."""
    ms = sorted(matrices, key=lambda m: m.as_of_date)
    if len(ms) < 2:
        raise ValueError("need at least 2 dated matrices to form a forward return")
    signals, forwards = [], []
    for i in range(len(ms) - 1):
        sig = _matrix_signal(ms[i], feature, apply_direction)
        fwd = _forward_returns(sig.keys(), ms[i].as_of_date, ms[i + 1].as_of_date,
                               close_fn, symbol_fn)
        signals.append(sig)
        forwards.append(fwd)
    return signals, forwards
