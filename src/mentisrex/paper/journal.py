"""Trade journal — append-only, durable record of everything the system did.

JSONL (one JSON object per line): append is atomic-enough per line, survives a
crash mid-run, needs no schema migration, and is trivially greppable. This is the
audit trail a paper/live system must keep and a backtest never needs — a backtest
can just be re-run, a live run cannot replay reality.

Every entry: {ts, kind, ...payload}. kinds: order, fill, reject, error, restart,
heartbeat. Read back for the dashboard and post-mortems.

ponytail: JSONL over a DB. Move to the DuckDB store pattern only if you need
indexed queries across millions of entries.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


class TradeJournal:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

    def record(self, kind: str, **payload) -> None:
        entry = {"ts": datetime.now(UTC).isoformat(), "kind": kind, **_jsonable(payload)}
        with self._path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def read(self, kind: str | None = None) -> list[dict]:
        out: list[dict] = []
        with self._path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                e = json.loads(line)
                if kind is None or e.get("kind") == kind:
                    out.append(e)
        return out


def _jsonable(d: dict) -> dict:
    """Decimals/datetimes to primitives so the line is valid JSON."""
    from decimal import Decimal

    def conv(v):
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list | tuple):
            return [conv(x) for x in v]
        return v

    return {k: conv(v) for k, v in d.items()}
