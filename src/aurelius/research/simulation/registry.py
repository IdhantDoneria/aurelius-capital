"""Experiment-registry attachment (AIDP M11).

Attaches a SimulationResult to its M7 experiment — full provenance, no rerun.
Key realized metrics land in the registry; the full result is written as a JSON
artifact and hash-recorded. Uses the existing store (full upsert), no schema change.
"""

from __future__ import annotations

from pathlib import Path

from aurelius.research.simulation import serialization


def attach_simulation(registry, experiment, result, *, artifacts_dir: str | None = None) -> dict:
    if registry is None or experiment is None:
        return {}
    d = Path(artifacts_dir or f"./data/simulation/{experiment.experiment_id}")
    d.mkdir(parents=True, exist_ok=True)
    path = d / "simulation_result.json"
    serialization.save_json(result, str(path))
    import hashlib
    h = hashlib.blake2b(path.read_bytes(), digest_size=16).hexdigest()

    exp = registry.load(experiment.experiment_id) or experiment
    s = result.summary
    exp.metrics = {**(exp.metrics or {}),
                   "SimCAGR": s.cagr, "SimSharpe": s.sharpe, "SimMaxDrawdown": s.max_drawdown,
                   "SimAnnualizedTurnover": s.annualized_turnover, "SimTotalCost": s.total_cost,
                   "SimFinalValue": s.final_value}
    exp.notes = f"simulation cagr={s.cagr:.3f} sharpe={s.sharpe:.2f} maxDD={s.max_drawdown:.3f} rebalances={s.n_rebalances}"
    exp.artifacts = [*(exp.artifacts or []),
                     {"artifact_type": "simulation_result.json", "artifact_location": str(path),
                      "artifact_hash": h}]
    registry.store.insert(exp)
    return {"artifact": str(path), "hash": h}
