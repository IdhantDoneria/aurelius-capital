"""Snapshot builders + point-in-time validation (AIDP M18).

Convenience construction of a `MarketDataSnapshot` and the PIT guard that rejects
look-ahead. `validate_pit` is the gate the engine calls before valuing: it rejects future
observations, missing valuation dates, stale data beyond tolerance and inconsistent
timestamps. This is where "never silently use future data" is enforced.
"""

from __future__ import annotations

from datetime import date

from aurelius.research.valuation.models import (
    MarketDataSnapshot,
    MarketQuote,
    Provenance,
)


def build_snapshot(as_of: date, *, spots=None, rates=None, vol_surfaces=None,
                   dividend_yields=None, forwards=None, fx_provider=None,
                   corporate_actions=None, source: str = "manual",
                   quotes=None) -> MarketDataSnapshot:
    return MarketDataSnapshot(
        as_of=as_of, spots=dict(spots or {}), rates=dict(rates or {}),
        vol_surfaces=dict(vol_surfaces or {}), dividend_yields=dict(dividend_yields or {}),
        forwards=dict(forwards or {}), fx_provider=fx_provider,
        corporate_actions=dict(corporate_actions or {}), quotes=dict(quotes or {}),
        provenance=Provenance(source=source, observation_date=as_of, effective_date=as_of))


def validate_pit(snap: MarketDataSnapshot, *, max_staleness_days: int | None = None) -> list:
    """Return PIT problems (empty == clean). Enforces the no-look-ahead guarantee."""
    problems = []
    if snap.as_of is None:
        return ["snapshot has no valuation date (as_of)"]

    def _check(prov: Provenance, label: str):
        if prov.observation_date and prov.observation_date > snap.as_of:
            problems.append(f"{label}: observation_date {prov.observation_date} is after "
                            f"valuation date {snap.as_of} (look-ahead)")
        if (max_staleness_days is not None and prov.observation_date
                and (snap.as_of - prov.observation_date).days > max_staleness_days):
            problems.append(f"{label}: data from {prov.observation_date} is stale vs "
                            f"{snap.as_of} (> {max_staleness_days}d)")
        if (prov.timestamp is not None and prov.observation_date is not None
                and prov.timestamp.date() != prov.observation_date):
            problems.append(f"{label}: timestamp {prov.timestamp} inconsistent with "
                            f"observation_date {prov.observation_date}")

    _check(snap.provenance, "snapshot")
    for iid, q in snap.quotes.items():
        if isinstance(q, MarketQuote):
            _check(q.provenance, f"quote[{iid}]")
    for cid, curve in snap.rates.items():
        if getattr(curve, "ref_date", snap.as_of) > snap.as_of:
            problems.append(f"curve[{cid}]: ref_date {curve.ref_date} after valuation date")
    for sid, surf in snap.vol_surfaces.items():
        if getattr(surf, "ref_date", snap.as_of) > snap.as_of:
            problems.append(f"surface[{sid}]: ref_date {surf.ref_date} after valuation date")
    return problems


def is_pit_safe(snap: MarketDataSnapshot, *, max_staleness_days: int | None = None) -> bool:
    return not validate_pit(snap, max_staleness_days=max_staleness_days)
