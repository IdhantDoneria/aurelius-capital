"""Artifact manager (AIDP M8).

Writes the canonical run artifacts, hashes each file, verifies integrity by
re-reading, and returns a manifest {filename: {location, hash}} that the pipeline
records in the registry. Deterministic JSON (sorted keys) so identical runs produce
byte-identical artifacts.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from mentisrex.research.execution.exceptions import ExecutionError

_ARTIFACTS = ("metrics.json", "config.json", "parameters.json", "summary.json",
              "equity_curve.csv", "positions.csv", "transactions.csv",
              "feature_manifest.json", "experiment_manifest.json")


class ArtifactManager:
    def __init__(self, base_dir: str) -> None:
        self.dir = Path(base_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def write_all(self, session) -> dict:
        cfg, exp = session.config, session.experiment
        pm = session.report.metrics if session.report else None

        self._json("metrics.json", session.metrics)
        self._json("config.json", {
            "name": cfg.name, "description": cfg.description, "parameters": cfg.parameters,
            "features": cfg.features, "dataset_versions": cfg.dataset_versions,
            "random_seed": cfg.random_seed, "policy": cfg.policy,
            "as_of": cfg.as_of.isoformat() if cfg.as_of else None,
        })
        self._json("parameters.json", cfg.parameters)
        self._json("summary.json", {
            "experiment_id": exp.experiment_id if exp else None,
            "session_id": session.session_id, "state": str(session.state),
            "stage_timings": session.stage_timings,
            "key_metrics": {k: session.metrics.get(k) for k in
                            ("Sharpe", "Sortino", "CAGR", "MaxDrawdown", "Volatility")},
        })
        self._equity_csv("equity_curve.csv", pm)
        self._positions_csv("positions.csv", pm)
        self._transactions_csv("transactions.csv", pm)
        self._json("feature_manifest.json", {
            "features": cfg.features,
            "feature_registry_version": cfg.dataset_versions.get("feature_registry_version"),
            "directions": getattr(session.matrix, "directions", {}) if session.matrix else {},
        })
        # tie-together manifest — links registry, dataset fingerprint, and artifacts
        manifest = self._manifest(session)
        self._json("experiment_manifest.json", {
            "experiment_id": exp.experiment_id if exp else None,
            "fingerprint": exp.fingerprint if exp else None,
            "git_commit": exp.git_commit if exp else None,
            "dataset_versions": cfg.dataset_versions,
            "state": str(session.state),
            "artifacts": manifest,
        })
        # experiment_manifest itself is the last file; hash+add it too
        manifest = self._manifest(session)
        self._verify(manifest)
        session.artifacts = manifest
        return manifest

    # ── writers ─────────────────────────────────────────────────────────────────

    def _json(self, name: str, obj) -> None:
        path = self.dir / name
        path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str))

    def _equity_csv(self, name: str, pm) -> None:
        rows = [("timestamp", "equity")]
        if pm:
            rows += [(p.timestamp.isoformat(), p.equity) for p in pm.equity_curve]
        self._csv(name, rows)

    def _positions_csv(self, name: str, pm) -> None:
        rows = [("symbol", "side", "entry_time", "exit_time", "quantity",
                 "entry_price", "exit_price", "pnl")]
        if pm:
            rows += [(t.symbol, t.side, t.entry_time.isoformat(), t.exit_time.isoformat(),
                      t.quantity, t.entry_price, t.exit_price, t.pnl) for t in pm.round_trips]
        self._csv(name, rows)

    def _transactions_csv(self, name: str, pm) -> None:
        rows = [("timestamp", "symbol", "action", "quantity", "price")]
        if pm:
            for t in pm.round_trips:
                rows.append((t.entry_time.isoformat(), t.symbol, f"open_{t.side}", t.quantity, t.entry_price))
                rows.append((t.exit_time.isoformat(), t.symbol, f"close_{t.side}", t.quantity, t.exit_price))
        self._csv(name, rows)

    def _csv(self, name: str, rows) -> None:
        with (self.dir / name).open("w", newline="") as f:
            csv.writer(f).writerows(rows)

    # ── hashing / integrity ─────────────────────────────────────────────────────

    def _manifest(self, session) -> dict:
        out = {}
        for name in _ARTIFACTS:
            path = self.dir / name
            if path.exists():
                out[name] = {"location": str(path), "hash": _file_hash(path)}
        return out

    def _verify(self, manifest: dict) -> None:
        for name, meta in manifest.items():
            if _file_hash(Path(meta["location"])) != meta["hash"]:
                raise ExecutionError(f"artifact integrity check failed: {name}")


def _file_hash(path: Path) -> str:
    return hashlib.blake2b(path.read_bytes(), digest_size=16).hexdigest()
