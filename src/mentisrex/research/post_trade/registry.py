"""Experiment-registry attachment (AIDP M15).

Attaches a post-trade session to its M7 experiment — full provenance, no rerun.
Mirrors M12/M14: key operational metrics into the registry, the full session JSON as a
hash-recorded artifact. Adds the post-trade leg to the existing research/simulation/
paper/execution lineage.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from mentisrex.research.post_trade import reporting, serialization
from mentisrex.research.post_trade.diagnostics import fingerprint as _fingerprint


def attach_post_trade(registry, experiment, engine, *, artifacts_dir: str | None = None) -> dict:
    if registry is None or experiment is None:
        return {}
    d = Path(artifacts_dir or f"./data/post_trade/{experiment.experiment_id}")
    d.mkdir(parents=True, exist_ok=True)
    path = d / "post_trade_session.json"
    serialization.save_json(engine, str(path))
    h = hashlib.blake2b(path.read_bytes(), digest_size=16).hexdigest()

    exp = registry.load(experiment.experiment_id) or experiment
    rep = reporting.post_trade_report(engine)
    exp.metrics = {
        **(exp.metrics or {}),
        "PostTradeValue": rep.portfolio_value,
        "PostTradeSettledCash": rep.settled_cash,
        "PostTradeRealizedPnL": rep.realized_pnl,
        "PostTradeSettlementCompletion": rep.settlement.n_completed
        / max(rep.settlement.n_completed + rep.settlement.n_pending + rep.settlement.n_failed, 1),
        "PostTradeHealthOK": float(rep.health.ok),
    }
    exp.notes = (
        f"post_trade trades={rep.ledger.n_trade_events} "
        f"settled={rep.settlement.n_completed} pending={rep.settlement.n_pending} "
        f"value={rep.portfolio_value:.0f} healthOK={rep.health.ok}"
    )
    exp.artifacts = [
        *(exp.artifacts or []),
        {
            "artifact_type": "post_trade_session.json",
            "artifact_location": str(path),
            "artifact_hash": h,
        },
    ]
    registry.store.insert(exp)
    return {"artifact": str(path), "hash": h, "session_fingerprint": _fingerprint(engine)}
