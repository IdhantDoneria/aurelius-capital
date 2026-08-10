"""Experiment-registry attachment (AIDP M16).

Attaches an FX-aware multi-currency session to its experiment — full provenance across
the research/simulation/paper/execution/post-trade/FX lineage. Mirrors M15
`attach_post_trade`: key base-currency metrics into the experiment, the full session
JSON as a hash-recorded artifact.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from aurelius.research.fx import serialization
from aurelius.research.fx.diagnostics import fingerprint as _fingerprint
from aurelius.research.fx.exposure import fx_exposure
from aurelius.research.fx.valuation import valuation


def attach_fx(registry, experiment, book, *, artifacts_dir: str | None = None, as_of=None) -> dict:
    if registry is None or experiment is None:
        return {}
    d = Path(artifacts_dir or f"./data/fx/{experiment.experiment_id}")
    d.mkdir(parents=True, exist_ok=True)
    path = d / "fx_session.json"
    serialization.save_json(book, str(path), as_of=as_of)
    h = hashlib.blake2b(path.read_bytes(), digest_size=16).hexdigest()

    exp = registry.load(experiment.experiment_id) or experiment
    val = valuation(book, as_of=as_of)
    exp_r = fx_exposure(book, as_of=as_of)
    exp.metrics = {**(exp.metrics or {}),
                   "FXBaseValue": val.total_base,
                   "FXBaseCash": val.cash_base,
                   "FXGrossExposure": exp_r.gross,
                   "FXNumCurrencies": float(len(book.currencies())),
                   "FXRealizedPnL": book.realized_fx_pnl}
    exp.notes = (f"fx base={book.base_currency} currencies={len(book.currencies())} "
                 f"value={val.total_base:.0f} gross_fx={exp_r.gross:.0f} "
                 f"conversions={len(book.conversions)}")
    exp.artifacts = [*(exp.artifacts or []),
                     {"artifact_type": "fx_session.json", "artifact_location": str(path),
                      "artifact_hash": h}]
    registry.store.insert(exp)
    return {"artifact": str(path), "hash": h, "session_fingerprint": _fingerprint(book)}
