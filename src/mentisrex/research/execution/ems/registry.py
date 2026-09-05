"""Experiment-registry attachment (AIDP M14).

Attaches an execution session to its M7 experiment — full provenance, no rerun.
Mirrors M12 `attach_session`: key execution-quality metrics land in the registry,
the full session JSON is written as a hash-recorded artifact. Reuses the experiment's
existing research/simulation/paper lineage; adds the execution leg.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from mentisrex.research.execution.ems import monitoring, serialization
from mentisrex.research.execution.ems.diagnostics import fingerprint as _fingerprint


def attach_execution(registry, experiment, session, *, artifacts_dir: str | None = None) -> dict:
    if registry is None or experiment is None:
        return {}
    d = Path(artifacts_dir or f"./data/execution/{experiment.experiment_id}")
    d.mkdir(parents=True, exist_ok=True)
    path = d / "execution_session.json"
    serialization.save_json(session, str(path))
    h = hashlib.blake2b(path.read_bytes(), digest_size=16).hexdigest()

    exp = registry.load(experiment.experiment_id) or experiment
    m = monitoring.metrics(session)
    exp.metrics = {
        **(exp.metrics or {}),
        "ExecFillRate": m.fill_rate,
        "ExecTotalCost": m.total_cost,
        "ExecTotalCostBps": m.total_cost_bps,
        "ExecAvgSlippageBps": m.avg_slippage_bps,
        "ExecImplementationShortfallBps": m.avg_implementation_shortfall_bps,
        "ExecNOrders": float(m.n_orders),
    }
    exp.notes = (
        f"execution orders={m.n_orders} filled={m.n_filled} fillRate={m.fill_rate:.2f} "
        f"costBps={m.total_cost_bps:.1f} slipBps={m.avg_slippage_bps:.1f}"
    )
    exp.artifacts = [
        *(exp.artifacts or []),
        {
            "artifact_type": "execution_session.json",
            "artifact_location": str(path),
            "artifact_hash": h,
        },
    ]
    registry.store.insert(exp)
    return {"artifact": str(path), "hash": h, "session_fingerprint": _fingerprint(session)}
