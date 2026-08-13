"""Experiment registry engine — authoritative source of truth (AIDP M7).

The public API. start → finish/fail bracket a run; every experiment is stamped
with automatic lineage and an immutable metadata fingerprint, so any run can be
searched, compared, and reproduced from stored metadata alone — years later, on
another machine, with no raw data retained.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from mentisrex.research.experiment_registry import hashing, lineage
from mentisrex.research.experiment_registry.models import Experiment
from mentisrex.research.experiment_registry.storage import RegistryStore
from mentisrex.research.experiment_registry.validation import detect_duplicate


class ExperimentRegistry:
    def __init__(self, db_path: str = "./data/research_registry.duckdb",
                 *, store: RegistryStore | None = None) -> None:
        self.store = store or RegistryStore(db_path)

    def close(self) -> None:
        self.store.close()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start_experiment(self, name: str, *, description: str = "",
                         parameters: dict | None = None, features: list[str] | None = None,
                         dataset_versions: dict | None = None, random_seed: int | None = None,
                         notes: str = "", capture_runtime: bool = True) -> Experiment:
        """Open an experiment. Lineage (git/python/OS/host/user) is auto-captured;
        the run identity fingerprint is computed and duplicates are tagged."""
        now = datetime.now(UTC)
        rt = lineage.capture_runtime() if capture_runtime else {}
        dv = dataset_versions or {}
        params = parameters or {}
        feats = list(features or [])
        fingerprint = hashing.experiment_fingerprint(dv, feats, params)
        exp = Experiment(
            experiment_id=uuid.uuid4().hex, name=name, status="running", description=description,
            random_seed=random_seed, created_at=now, started_at=now, notes=notes,
            dataset_versions=dv, parameters=params, features=feats,
            fingerprint=fingerprint, parameter_hash=hashing.hash_params(params),
            duplicate_of=detect_duplicate(self.store, fingerprint),
            git_commit=rt.get("git_commit"), git_branch=rt.get("git_branch"),
            python_version=rt.get("python_version"), platform=rt.get("platform"),
            hostname=rt.get("hostname"), user=rt.get("user"),
        )
        self.store.insert(exp)
        return exp

    def finish_experiment(self, exp: Experiment | str, *, metrics: dict | None = None,
                          artifacts: list[dict] | None = None, notes: str | None = None) -> Experiment:
        exp = self._resolve(exp)
        exp.finished_at = datetime.now(UTC)
        exp.duration_seconds = self._elapsed(exp)
        exp.status = "finished"
        if metrics is not None:
            exp.metrics = metrics
        if artifacts is not None:
            exp.artifacts = artifacts
        if notes is not None:
            exp.notes = notes
        self.store.update_run(exp)
        return exp

    def fail_experiment(self, exp: Experiment | str, error: BaseException | str, *,
                        notes: str | None = None) -> Experiment:
        """Record a failure. The registry stays consistent — status=failed + the
        exception text, nothing half-written."""
        exp = self._resolve(exp)
        exp.finished_at = datetime.now(UTC)
        exp.duration_seconds = self._elapsed(exp)
        exp.status = "failed"
        exp.error = f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error)
        if notes is not None:
            exp.notes = notes
        self.store.update_run(exp)
        return exp

    # ── queries ───────────────────────────────────────────────────────────────

    def load(self, experiment_id: str) -> Experiment | None:
        return self.store.get(experiment_id)

    def latest(self) -> Experiment | None:
        return self.store.latest()

    def search(self, **filters) -> list[Experiment]:
        return self.store.search(**filters)

    def compare(self, exp1: Experiment | str, exp2: Experiment | str) -> dict:
        """Metric deltas + what changed between two experiments."""
        a, b = self._resolve(exp1), self._resolve(exp2)
        metrics = {}
        for k in sorted(set(a.metrics) | set(b.metrics)):
            va, vb = a.metrics.get(k), b.metrics.get(k)
            metrics[k] = {"a": va, "b": vb,
                          "delta": (vb - va) if (va is not None and vb is not None) else None}
        return {
            "experiment_a": a.experiment_id, "experiment_b": b.experiment_id,
            "metrics": metrics,
            "same_fingerprint": a.fingerprint == b.fingerprint,
            "parameters_changed": a.parameter_hash != b.parameter_hash,
            "dataset_changed": a.dataset_versions != b.dataset_versions,
            "features_changed": sorted(a.features) != sorted(b.features),
        }

    def reproduce(self, experiment_id: str) -> dict:
        """Ready-to-run experiment definition rebuilt from stored metadata: the
        exact dataset versions, feature list, parameters, and matrix version. Feed
        this back into start_experiment to re-run the identical configuration."""
        exp = self.store.get(experiment_id)
        if exp is None:
            raise KeyError(f"experiment {experiment_id} not found")
        return {
            "name": exp.name,
            "description": exp.description,
            "dataset_versions": exp.dataset_versions,
            "research_matrix_version": exp.dataset_versions.get("research_matrix_version"),
            "features": exp.features,
            "parameters": exp.parameters,
            "random_seed": exp.random_seed,
            "git_commit": exp.git_commit,
            "fingerprint": exp.fingerprint,
        }

    # ── helpers ───────────────────────────────────────────────────────────────

    def _resolve(self, exp: Experiment | str) -> Experiment:
        if isinstance(exp, Experiment):
            return exp
        got = self.store.get(exp)
        if got is None:
            raise KeyError(f"experiment {exp} not found")
        return got

    @staticmethod
    def _elapsed(exp: Experiment) -> float:
        if exp.started_at is None or exp.finished_at is None:
            return 0.0
        return (exp.finished_at - exp.started_at).total_seconds()
