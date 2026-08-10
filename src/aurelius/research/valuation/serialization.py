"""Deterministic serialization (AIDP M18).

ValuationResult / PortfolioValuation / curve / snapshot → JSON. Sorted keys, rounded money,
governance fingerprints preserved. Two identical valuations serialize byte-identically — the
reproducibility guarantee. Reuses the M15 `_clean` recursive normalizer.
"""

from __future__ import annotations

import json

from aurelius.research.post_trade.serialization import _clean


def result_to_dict(res) -> dict:
    return {
        "instrument_id": res.instrument_id,
        "valuation_date": str(res.valuation_date),
        "price": round(res.price, 10),
        "market_value": round(res.market_value, 6),
        "currency": res.currency,
        "base_value": round(res.base_value, 6),
        "quantity": res.quantity,
        "pnl": round(res.pnl, 6),
        "model_name": res.model_name,
        "model_version": res.model_version,
        "input_fingerprint": res.input_fingerprint,
        "market_data_fingerprint": res.market_data_fingerprint,
        "greeks": _clean(res.greeks) if res.greeks is not None else None,
        "assumptions": _clean(res.assumptions),
        "reproducible_key": res.reproducible_key,
    }


def portfolio_to_dict(pv) -> dict:
    return {
        "valuation_date": str(pv.valuation_date),
        "base_currency": pv.base_currency,
        "gross_market_value": round(pv.gross_market_value, 6),
        "net_market_value": round(pv.net_market_value, 6),
        "base_value": round(pv.base_value, 6),
        "unrealized_pnl": round(pv.unrealized_pnl, 6),
        "greeks": _clean(pv.greeks) if pv.greeks else None,
        "risk_inputs": {k: round(v, 6) if isinstance(v, float) else v
                        for k, v in sorted(pv.risk_inputs.items())},
        "market_data_fingerprint": pv.market_data_fingerprint,
        "results": [result_to_dict(r) for r in pv.results],
    }


def to_json(obj, *, indent: int = 2) -> str:
    d = portfolio_to_dict(obj) if hasattr(obj, "results") else result_to_dict(obj)
    return json.dumps(d, indent=indent, sort_keys=True, default=str)


def curve_to_dict(curve) -> dict:
    return {"curve_id": curve.curve_id, "ref_date": str(curve.ref_date),
            "tenors": list(curve.tenors),
            "zeros": list(getattr(curve, "zeros", [])) or None,
            "dfs": list(getattr(curve, "dfs", [])) or None,
            "fingerprint": curve.fingerprint()}
