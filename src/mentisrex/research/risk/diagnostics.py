"""Risk diagnostics (AIDP M13) — flat, deterministic health dict for a RiskReport."""

from __future__ import annotations

import hashlib
import json

from mentisrex.research.risk import serialization


def diagnostics(report) -> dict:
    return {
        "decision": report.decision.value,
        "volatility": report.volatility,
        "gross": report.exposure.gross,
        "net": report.exposure.net,
        "herfindahl": report.concentration.herfindahl,
        "effective_holdings": report.concentration.effective_holdings,
        "var_95": (report.var.var.get("95%") if report.var else None),
        "max_drawdown": (report.drawdown.max_drawdown if report.drawdown else None),
        "n_violations": len(report.violations),
        "n_hard": sum(1 for v in report.violations if v.severity == "hard"),
        "n_warnings": len(report.warnings),
        "fingerprint": fingerprint(report),
    }


def fingerprint(report) -> str:
    d = serialization.report_to_dict(report)
    d.pop("generated_at", None)  # exclude wall-clock → deterministic
    body = json.dumps(d, sort_keys=True, default=str)
    return hashlib.blake2b(body.encode(), digest_size=16).hexdigest()
