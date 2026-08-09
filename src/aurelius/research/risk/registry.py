"""Experiment-registry attachment (AIDP M13).

Attaches a risk assessment to its M7 experiment — provenance, timestamp, config,
hash. Mirrors M11 `attach_simulation` / M12 `attach_session`: key risk metrics land
in the registry and the full RiskReport JSON is written as a hash-recorded artifact.
The same experiment can carry research → simulation → paper → risk legs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from aurelius.research.risk import serialization
from aurelius.research.risk.diagnostics import diagnostics as _diagnostics


def attach_risk(registry, experiment, report, *, artifacts_dir: str | None = None) -> dict:
    if registry is None or experiment is None:
        return {}
    d = Path(artifacts_dir or f"./data/risk/{experiment.experiment_id}")
    d.mkdir(parents=True, exist_ok=True)
    path = d / "risk_report.json"
    serialization.save_json(report, str(path))
    h = hashlib.blake2b(path.read_bytes(), digest_size=16).hexdigest()

    exp = registry.load(experiment.experiment_id) or experiment
    diag = _diagnostics(report)
    exp.metrics = {**(exp.metrics or {}),
                   "RiskDecision": {"approve": 1.0, "approve_with_warning": 0.5, "reject": 0.0}
                   .get(diag["decision"], 0.0),
                   "RiskVolatility": diag["volatility"], "RiskGross": diag["gross"],
                   "RiskHerfindahl": diag["herfindahl"],
                   "RiskVaR95": diag["var_95"] or 0.0,
                   "RiskViolations": float(diag["n_violations"])}
    exp.notes = (f"risk decision={diag['decision']} vol={diag['volatility']:.3f} "
                 f"gross={diag['gross']:.2f} violations={diag['n_violations']}")
    exp.artifacts = [*(exp.artifacts or []),
                     {"artifact_type": "risk_report.json", "artifact_location": str(path),
                      "artifact_hash": h}]
    registry.store.insert(exp)
    return {"artifact": str(path), "hash": h, "risk_fingerprint": diag["fingerprint"]}
