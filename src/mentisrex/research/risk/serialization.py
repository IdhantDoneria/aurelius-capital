"""Deterministic serialization (AIDP M13). RiskReport → sorted-key JSON."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path


def _enum(v):
    return v.value if hasattr(v, "value") else v


def report_to_dict(report) -> dict:
    d = asdict(report)
    d["decision"] = _enum(report.decision)
    d["as_of"] = report.as_of.isoformat() if report.as_of else None
    d["generated_at"] = report.generated_at.isoformat() if report.generated_at else None
    d["violations"] = [{**asdict(v), "message": v.message} for v in report.violations]
    return d


def to_json(report, *, indent: int = 2) -> str:
    payload = report_to_dict(report) if is_dataclass(report) else report
    return json.dumps(payload, indent=indent, sort_keys=True, default=str)


def save_json(report, path: str) -> str:
    Path(path).write_text(to_json(report))
    return path
