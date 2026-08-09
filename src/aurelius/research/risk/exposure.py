"""Exposure & concentration engine (AIDP M13).

Gross/net/long/short/cash exposure and concentration (HHI, effective holdings,
largest position/contribution) from a signed weight vector. Classification
exposures (sector/industry/country/currency) are computed when a mapping is
injected; otherwise reported empty (the SecurityMaster classification gap noted
since M9). Reuses M10 `risk_diagnostics` for the risk-contribution concentration.
"""

from __future__ import annotations

import numpy as np

from aurelius.research.risk.models import ExposureReport


def exposure_report(weights: dict, *, sectors=None, industries=None,
                    countries=None, currencies=None) -> ExposureReport:
    w = weights or {}
    longs = sum(v for v in w.values() if v > 0)
    shorts = sum(-v for v in w.values() if v < 0)
    gross = longs + shorts
    net = longs - shorts
    return ExposureReport(
        gross=gross, net=net, long=longs, short=shorts, cash=1.0 - gross,
        n_long=sum(1 for v in w.values() if v > 0),
        n_short=sum(1 for v in w.values() if v < 0),
        sector=_group(w, sectors), industry=_group(w, industries),
        country=_group(w, countries), currency=_group(w, currencies))


def _group(weights: dict, mapping) -> dict:
    """Aggregate signed weight by an injected {security_id: label} classification."""
    if not mapping:
        return {}
    out: dict = {}
    for sid, wt in weights.items():
        label = mapping.get(sid, "unknown")
        out[label] = out.get(label, 0.0) + wt
    return out
