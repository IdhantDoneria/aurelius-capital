"""Deterministic serialization (AIDP M19).

Observations, curves, credit curves, vol surfaces, calibration reports, provenance and
diagnostics → JSON and back. Reuses the M15 `_clean` recursive normalizer (dataclass→dict,
enum→value, date→ISO) and sorted-key JSON, so two identical artifacts serialize byte-identically.
Round-trip (`*_to_dict` → `*_from_dict`) preserves fingerprints and numerical values — the
reproducibility guarantee extended down to the market-data layer.
"""

from __future__ import annotations

import json
from datetime import date

from mentisrex.research.market_data.credit import CreditCurve
from mentisrex.research.market_data.models import (
    CanonicalObservation,
    ObservationType,
    QualityStatus,
    Unit,
)
from mentisrex.research.post_trade.serialization import _clean
from mentisrex.research.valuation.curves import DiscountCurve, ZeroCurve
from mentisrex.research.valuation.daycount import Compounding, DayCount
from mentisrex.research.valuation.volatility import VolatilitySurface


# ── observations ──────────────────────────────────────────────────────────────

def observation_to_dict(o: CanonicalObservation) -> dict:
    return {"security_id": o.security_id, "obs_type": o.obs_type.value, "field": o.field,
            "value": o.value, "observation_date": o.observation_date.isoformat(),
            "effective_date": o.effective_date.isoformat(), "source": o.source,
            "timestamp": o.timestamp.isoformat() if o.timestamp else None,
            "currency": o.currency, "unit": o.unit.value, "status": o.status.value,
            "revision": o.revision, "meta": _clean(o.meta), "fingerprint": o.fingerprint()}


def observation_from_dict(d: dict) -> CanonicalObservation:
    from datetime import datetime
    return CanonicalObservation(
        security_id=d["security_id"], obs_type=ObservationType(d["obs_type"]), field=d["field"],
        value=d["value"], observation_date=date.fromisoformat(d["observation_date"]),
        effective_date=date.fromisoformat(d["effective_date"]), source=d["source"],
        timestamp=datetime.fromisoformat(d["timestamp"]) if d.get("timestamp") else None,
        currency=d.get("currency"), unit=Unit(d["unit"]), status=QualityStatus(d["status"]),
        revision=d.get("revision", 0), meta=dict(d.get("meta") or {}))


# ── curves ────────────────────────────────────────────────────────────────────

def curve_to_dict(c) -> dict:
    kind = "discount" if isinstance(c, DiscountCurve) else "zero"
    return {"kind": kind, "curve_id": c.curve_id, "ref_date": c.ref_date.isoformat(),
            "tenors": list(c.tenors),
            "values": list(getattr(c, "zeros", getattr(c, "dfs", ()))),
            "compounding": c.compounding.value, "day_count": c.day_count.value,
            "currency": c.currency, "fingerprint": c.fingerprint()}


def curve_from_dict(d: dict):
    cls = DiscountCurve if d["kind"] == "discount" else ZeroCurve
    return cls(d["curve_id"], date.fromisoformat(d["ref_date"]), tuple(d["tenors"]),
              tuple(d["values"]), Compounding(d["compounding"]), DayCount(d["day_count"]),
              currency=d["currency"])


def credit_curve_to_dict(c: CreditCurve) -> dict:
    return {"curve_id": c.curve_id, "tenors": list(c.tenors), "hazards": list(c.hazards),
            "recovery": c.recovery, "currency": c.currency, "fingerprint": c.fingerprint()}


def credit_curve_from_dict(d: dict) -> CreditCurve:
    return CreditCurve(d["curve_id"], tuple(d["tenors"]), tuple(d["hazards"]),
                       d["recovery"], d["currency"])


# ── vol surface ───────────────────────────────────────────────────────────────

def surface_to_dict(s: VolatilitySurface) -> dict:
    return {"surface_id": s.surface_id, "ref_date": s.ref_date.isoformat(),
            "strikes": list(s.strikes), "maturities": list(s.maturities),
            "grid": [list(r) for r in s.grid], "fingerprint": s.fingerprint()}


def surface_from_dict(d: dict) -> VolatilitySurface:
    return VolatilitySurface(d["surface_id"], date.fromisoformat(d["ref_date"]),
                             tuple(d["strikes"]), tuple(d["maturities"]),
                             tuple(tuple(r) for r in d["grid"]))


# ── reports / provenance / generic ────────────────────────────────────────────

def report_to_dict(r) -> dict:
    return {"curve_id": r.curve_id, "instruments": list(r.instruments),
            "max_repricing_error": r.diagnostics.max_repricing_error,
            "n_instruments": r.diagnostics.n_instruments,
            "converged": r.diagnostics.converged, "problems": list(r.problems), "ok": r.ok}


def to_json(obj, *, indent: int = 2) -> str:
    return json.dumps(_clean(obj), indent=indent, sort_keys=True, default=str)


def observations_to_json(observations, *, indent: int = 2) -> str:
    return json.dumps([observation_to_dict(o) for o in observations],
                      indent=indent, sort_keys=True, default=str)
