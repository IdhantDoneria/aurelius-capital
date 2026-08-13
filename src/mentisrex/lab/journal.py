"""Laboratory audit trail — append-only, durable, greppable.

Every job start/finish/skip/failure and every cycle boundary lands here as one
JSON line. This is the reproducibility record: months of autonomous operation
must be reconstructable from this file alone. Same JSONL rationale as the trade
journal — atomic-enough per line, survives a crash mid-cycle, no migrations.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path


class LabJournal:
    def __init__(self, path: str | Path = "./data/lab_journal.jsonl") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

    def log(self, kind: str, cycle_id: str, **payload) -> None:
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "kind": kind,  # cycle_start | cycle_complete | job
            "cycle_id": cycle_id,
            **_jsonable(payload),
        }
        with self._path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def read(self, cycle_id: str | None = None, kind: str | None = None) -> list[dict]:
        out: list[dict] = []
        with self._path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                e = json.loads(line)
                if cycle_id and e.get("cycle_id") != cycle_id:
                    continue
                if kind and e.get("kind") != kind:
                    continue
                out.append(e)
        return out

    def recent_cycles(self, n: int = 10) -> list[dict]:
        """Summaries of the most recent cycles, newest first."""
        completes = self.read(kind="cycle_complete")
        return list(reversed(completes[-n:]))

    def failure_rate(self, last_n_cycles: int = 20) -> dict:
        """Job failure/skip rates across recent cycles — queue-health signal."""
        cycles = self.recent_cycles(last_n_cycles)
        ids = {c["cycle_id"] for c in cycles}
        counts: dict[str, int] = defaultdict(int)
        for e in self.read(kind="job"):
            if e["cycle_id"] in ids:
                counts[e.get("status", "unknown")] += 1
        total = sum(counts.values())
        return {
            "cycles_considered": len(cycles),
            "jobs": dict(counts),
            "job_failure_rate": round(counts.get("failed", 0) / total, 3) if total else 0.0,
        }


def _jsonable(d: dict):
    from decimal import Decimal

    def conv(v):
        if isinstance(v, Decimal):
            return float(v)
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, list | tuple | set):
            return [conv(x) for x in v]
        return v

    return {k: conv(v) for k, v in d.items()}


if __name__ == "__main__":
    import tempfile

    j = LabJournal(Path(tempfile.mkdtemp()) / "j.jsonl")
    j.log("cycle_start", "c1")
    j.log("job", "c1", step="discover", status="skipped", reason="no source")
    j.log("job", "c1", step="generate", status="ok", generated=3)
    j.log("cycle_complete", "c1", ok=1, skipped=1, failed=0)
    assert len(j.read(cycle_id="c1")) == 4
    assert j.recent_cycles()[0]["cycle_id"] == "c1"
    assert j.failure_rate()["jobs"]["ok"] == 1
    print("lab journal self-check ok:", j.failure_rate())
