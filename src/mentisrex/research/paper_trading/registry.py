"""Experiment-registry attachment (AIDP M12).

Attaches a paper-trading session to its M7 experiment — full provenance, no rerun.
Mirrors M11 `attach_simulation`: key realized metrics land in the registry, the
full session JSON is written as a hash-recorded artifact. The experiment already
carries the research/simulation lineage; this just adds the paper-trading leg.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from mentisrex.research.paper_trading import serialization
from mentisrex.research.paper_trading.diagnostics import diagnostics as _diagnostics
from mentisrex.research.paper_trading.monitoring import monitoring_report as _monitoring_report


def attach_session(registry, experiment, session, *, artifacts_dir: str | None = None) -> dict:
    if registry is None or experiment is None:
        return {}
    d = Path(artifacts_dir or f"./data/paper_trading/{experiment.experiment_id}")
    d.mkdir(parents=True, exist_ok=True)
    path = d / "paper_session.json"
    serialization.save_json(session, str(path))
    h = hashlib.blake2b(path.read_bytes(), digest_size=16).hexdigest()

    exp = registry.load(experiment.experiment_id) or experiment
    mon = _monitoring_report(session)
    diag = _diagnostics(session)
    exp.metrics = {
        **(exp.metrics or {}),
        "PaperReconciliationRate": mon.reconciliation_rate,
        "PaperMaxWeightDrift": mon.max_weight_drift,
        "PaperTotalCost": mon.total_cost,
        "PaperFinalValue": diag["final_value"],
        "PaperNSyncs": float(mon.n_syncs),
    }
    exp.notes = (
        f"paper_trading syncs={mon.n_syncs} reconciled={mon.reconciliation_rate:.2f} "
        f"maxDrift={mon.max_weight_drift:.3f} finalValue={diag['final_value']:.0f}"
    )
    exp.artifacts = [
        *(exp.artifacts or []),
        {"artifact_type": "paper_session.json", "artifact_location": str(path), "artifact_hash": h},
    ]
    registry.store.insert(exp)
    return {"artifact": str(path), "hash": h, "session_fingerprint": session.fingerprint()}
