"""Deterministic serialization (AIDP M11).

JSON (full result, metadata-preserving) and Parquet (equity curve + trades, the
large series). Arrow is a documented future target. Round-trips without losing the
summary/metadata.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path


def to_dict(result) -> dict:
    return {
        "summary": asdict(result.summary),
        "metadata": _meta(result.metadata),
        "equity_curve": [asdict(e) | {"date": e.date.isoformat()} for e in result.equity_curve],
        "rebalance_events": [
            asdict(r) | {"date": r.date.isoformat()} for r in result.rebalance_events
        ],
        "cost_report": asdict(result.cost_report),
        "turnover_report": asdict(result.turnover_report),
        "exposure_report": asdict(result.exposure_report),
        "drawdown_report": asdict(result.drawdown_report),
        "capacity_report": asdict(result.capacity_report),
        "attribution": asdict(result.attribution),
        "diagnostics": result.diagnostics,
        "validation": result.validation,
        "n_trades": len(result.trades),
    }


def to_json(result, *, indent: int = 2) -> str:
    return json.dumps(to_dict(result), indent=indent, sort_keys=True, default=str)


def save_json(result, path: str) -> str:
    Path(path).write_text(to_json(result))
    return path


def save_parquet(result, directory: str) -> dict:
    """Write the heavy series to parquet; returns written paths. Requires pandas."""
    import pandas as pd

    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    eq = pd.DataFrame(
        [
            {
                "date": e.date.isoformat(),
                "value": e.value,
                "cash": e.cash,
                "gross": e.gross_exposure,
                "net": e.net_exposure,
            }
            for e in result.equity_curve
        ]
    )
    tr = pd.DataFrame(
        [
            {
                "date": t.date.isoformat() if t.date else None,
                "security_id": t.security_id,
                "quantity": t.quantity,
                "price": t.price,
                "cost": t.cost,
                "notional": t.notional,
            }
            for t in result.trades
        ]
    )
    eq_path, tr_path = d / "equity_curve.parquet", d / "trades.parquet"
    eq.to_parquet(eq_path)
    tr.to_parquet(tr_path)
    return {"equity_curve": str(eq_path), "trades": str(tr_path)}


def _meta(m) -> dict:
    out = asdict(m)
    out["start_date"] = m.start_date.isoformat() if m.start_date else None
    out["end_date"] = m.end_date.isoformat() if m.end_date else None
    return out
