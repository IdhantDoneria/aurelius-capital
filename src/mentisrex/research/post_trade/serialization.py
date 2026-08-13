"""Deterministic serialization (AIDP M15).

Engine → JSON: the full event log, ledgers, settlement records, and the composite
post-trade report. Sorted keys, stable ordering, round-trip stable — a post-trade
session is replayable and hash-comparable. Same style as M11–M14 serialization.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

from mentisrex.research.post_trade import reporting


def _clean(obj):
    """Recursively make a value JSON-stable: dataclasses → dicts, enums → values,
    dates → ISO strings."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _clean(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if hasattr(obj, "value") and hasattr(obj, "name"):        # enum
        return obj.value
    if hasattr(obj, "isoformat"):                             # date/datetime
        return obj.isoformat()
    return obj


def to_dict(engine) -> dict:
    from mentisrex.research.post_trade.diagnostics import diagnostics as _diag
    return {
        "session_id": engine.session_id,
        "initial_capital": engine.initial_capital,
        "events": [_clean(e) | {"event_type": type(e).__name__} for e in engine.log.events],
        "trades": {tid: st.value for tid, st in engine.trades.items()},
        "cash_events": [_clean(e) for e in engine.cash_ledger.events],
        "settlement_records": [_clean(r) for r in engine.settlement.records.values()],
        "report": _clean(reporting.post_trade_report(engine)),
        "diagnostics": _diag(engine),
    }


def to_json(engine, *, indent: int = 2) -> str:
    return json.dumps(to_dict(engine), indent=indent, sort_keys=True, default=str)


def save_json(engine, path: str) -> str:
    Path(path).write_text(to_json(engine))
    return path
