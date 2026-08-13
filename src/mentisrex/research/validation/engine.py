"""ResearchValidator — the final quality gate (AIDP M9).

Orchestrates every validator into one ValidationReport and wires the result back
into the platform: the report becomes an experiment artifact and the registry
records the validation score, verdict, and version. No strategy is deployable
without passing here.

Composition + dependency injection only — reuses M6 (research matrix), M7
(registry), and the certified PerformanceMetrics. Never re-runs a backtest itself
(re-fitting probes take an injected `evaluator`). Never introduces look-ahead: every
statistic is a function of the realized in-sample series.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from mentisrex.core.logging import get_logger
from mentisrex.research.validation import (
    bootstrap,
    capacity,
    diagnostics,
    factor_exposure,
    monte_carlo,
    multiple_testing,
    overfitting,
    permutation,
    report as report_mod,
    robustness as robustness_mod,
    scoring,
    stability,
    turnover,
    visualization,
)
from mentisrex.research.validation.report import ValidationReport
from mentisrex.research.validation.significance import sharpe, significance

logger = get_logger(__name__)

VALIDATION_VERSION = "1.0.0"


@dataclass
class ValidationConfig:
    bootstrap_samples: int = 1000
    bootstrap_method: str = "stationary"
    monte_carlo_samples: int = 1000
    permutation_samples: int = 1000
    n_trials: int = 1                       # # of configs tried (for DSR/Bonferroni)
    seed: int = 0
    aum: float = 1e8
    adv: float | None = None
    review_threshold: float = 50.0
    p_threshold: float = 0.05
    weights: dict = field(default_factory=dict)


class ResearchValidator:
    def __init__(self, *, config: ValidationConfig | None = None, registry=None) -> None:
        self.config = config or ValidationConfig()
        self.registry = registry

    def validate(self, experiment, execution_result, research_matrix=None, *,
                 benchmark_returns=None, evaluator=None, param=None, param_values=None,
                 returns_matrix=None, excess_matrix=None, positions=None,
                 artifacts_dir=None) -> ValidationReport:
        try:
            return self._validate(experiment, execution_result, research_matrix,
                                  benchmark_returns, evaluator, param, param_values,
                                  returns_matrix, excess_matrix, positions, artifacts_dir)
        except Exception as exc:  # noqa: BLE001 — validation must never crash the caller
            logger.error("validation_failed", error=str(exc))
            rep = ValidationReport(
                overall_verdict="REQUIRES_REVIEW", confidence_score=0.0,
                deployment_recommendation="Validation errored — manual review required.",
                critical_failures=[f"validation error: {type(exc).__name__}: {exc}"],
                validation_version=VALIDATION_VERSION)
            rep.manifest_hash = report_mod.manifest_hash(rep)
            return rep

    # ── core ──────────────────────────────────────────────────────────────────

    def _validate(self, experiment, execution_result, matrix, benchmark_returns, evaluator,
                  param, param_values, returns_matrix, excess_matrix, positions, artifacts_dir):
        cfg = self.config
        pm = _extract_pm(execution_result)
        returns = list(pm.daily_returns or [])
        timestamps = _timestamps(pm)

        if len(returns) < 3:
            rep = ValidationReport(
                overall_verdict="REQUIRES_REVIEW", confidence_score=0.0,
                deployment_recommendation="Too few return observations to validate.",
                critical_failures=["insufficient return history (<3 observations)"],
                validation_version=VALIDATION_VERSION)
            rep.manifest_hash = report_mod.manifest_hash(rep)
            return rep

        # ── statistical ──
        sig = significance(returns)
        boot = bootstrap.bootstrap_ci(returns, sharpe, n_samples=cfg.bootstrap_samples,
                                      method=cfg.bootstrap_method, seed=cfg.seed)
        mc = monte_carlo.monte_carlo(returns, sharpe, n_samples=cfg.monte_carlo_samples, seed=cfg.seed)
        # sign permutation: Sharpe is order-invariant, so a *return* permutation is
        # degenerate for it; randomizing the sign is the meaningful null for "is the
        # positive drift beyond chance?".
        perm = permutation.permutation_test(returns, sharpe, kind="sign",
                                            n_samples=cfg.permutation_samples, seed=cfg.seed)

        # ── overfitting ──
        of = overfitting.deflated_sharpe_ratio(returns, n_trials=cfg.n_trials)
        of.update({"psr": overfitting.probabilistic_sharpe_ratio(returns)["psr"]})
        if returns_matrix is not None:
            of["pbo"] = overfitting.pbo_cscv(returns_matrix).get("pbo")
        else:
            of["pbo_skipped"] = "no candidate-config returns matrix (see docs)"
        if excess_matrix is not None:
            of["reality_check"] = overfitting.whites_reality_check(excess_matrix, seed=cfg.seed)
        else:
            of["reality_check_skipped"] = "no multi-strategy excess matrix (see docs)"

        # ── multiple testing over the computed p-value family + Bonferroni on n_trials ──
        family = [sig["p_value"], perm["p_value"], boot.get("prob_le_zero", 1.0)]
        mt = {"family_pvalues": family,
              "bonferroni": multiple_testing.bonferroni(family)["adjusted"],
              "holm": multiple_testing.holm(family)["adjusted"],
              "benjamini_hochberg": multiple_testing.benjamini_hochberg(family)["adjusted"],
              "single_pvalue_bonferroni_n_trials": min(sig["p_value"] * cfg.n_trials, 1.0)}

        # ── robustness / stability ──
        rob = robustness_mod.robustness_summary(returns, timestamps, evaluator=evaluator,
                                                param=param, param_values=param_values, seed=cfg.seed)
        stab = (stability.stability_curve(evaluator, param, param_values)
                if (evaluator and param and param_values)
                else {"insufficient_data": True, "reason": "no evaluator/param grid"})

        # ── capacity / turnover / risk ──
        turn = turnover.turnover_profile(pm)
        cap = capacity.capacity_analysis(pm, aum=cfg.aum, adv=cfg.adv)
        factor = {
            "market": factor_exposure.market_exposure(returns, benchmark_returns),
            "style": factor_exposure.style_exposure(positions, matrix),
            "concentration": factor_exposure.concentration(positions) if positions else {"insufficient_data": True},
            **factor_exposure.unsupported_exposures(),
        }

        summaries = {
            "significance": sig, "bootstrap": boot, "monte_carlo": mc, "permutation": perm,
            "overfitting": of, "multiple_testing": mt, "robustness": rob, "stability": stab,
            "turnover": turn, "capacity": cap, "factor": factor,
        }

        flags = diagnostics.diagnose(summaries)
        score_result = scoring.score(summaries, experiment, weights=cfg.weights)
        decision = report_mod.decide(score_result, flags, summaries,
                                     review_threshold=cfg.review_threshold, p_threshold=cfg.p_threshold)
        visuals = visualization.build_visualizations(pm, summaries=summaries)

        rep = ValidationReport(
            overall_verdict=decision["verdict"],
            confidence_score=decision["confidence_score"],
            deployment_recommendation=decision["deployment_recommendation"],
            warnings=decision["warnings"], critical_failures=decision["critical_failures"],
            statistical_summary=_strip({"significance": sig, "bootstrap": boot,
                                        "monte_carlo": mc, "permutation": perm, "multiple_testing": mt}),
            robustness_summary=_strip({"robustness": rob, "stability": stab}),
            capacity_summary={"capacity": cap, "turnover": turn},
            risk_summary=factor,
            overfitting_summary=of,
            visualizations=visuals,
            execution_metadata={
                "experiment_id": getattr(experiment, "experiment_id", None),
                "fingerprint": getattr(experiment, "fingerprint", None),
                "git_commit": getattr(experiment, "git_commit", None),
                "validated_at": datetime.now(UTC).isoformat(),
                "validation_version": VALIDATION_VERSION, "seed": cfg.seed,
                "n_observations": len(returns),
            },
            research_score=score_result["research_score"],
            component_scores=score_result["components"],
            score_contributions=score_result["contributions"],
            diagnostics=[f.to_dict() for f in flags],
            reasoning=decision["reasoning"],
            validation_version=VALIDATION_VERSION,
        )
        rep.manifest_hash = report_mod.manifest_hash(rep)

        self._write_artifacts(rep, execution_result, experiment, artifacts_dir)
        self._update_registry(rep, experiment)
        return rep

    # ── integration ───────────────────────────────────────────────────────────

    def _write_artifacts(self, rep, execution_result, experiment, artifacts_dir) -> None:
        d = artifacts_dir or _default_dir(execution_result, experiment)
        path = Path(d)
        path.mkdir(parents=True, exist_ok=True)
        files = {
            "validation_report.json": json.dumps(rep.to_dict(), indent=2, sort_keys=True, default=str),
            "validation_visuals.json": json.dumps(rep.visualizations["charts"], indent=2, sort_keys=True, default=str),
            "plot_validation.py": rep.visualizations["plotting_code"],
        }
        manifest = {}
        for name, content in files.items():
            fp = path / name
            fp.write_text(content)
            manifest[name] = {"location": str(fp),
                              "hash": hashlib.blake2b(fp.read_bytes(), digest_size=16).hexdigest()}
        rep.execution_metadata["artifacts"] = manifest

    def _update_registry(self, rep, experiment) -> None:
        if self.registry is None or experiment is None:
            return
        exp = self.registry.load(experiment.experiment_id) or experiment
        exp.metrics = {**(exp.metrics or {}),
                       "ValidationScore": float(rep.research_score),
                       "DeflatedSharpe": float(rep.overfitting_summary.get("dsr") or 0.0)}
        exp.notes = f"validation={rep.overall_verdict} v{rep.validation_version} score={rep.research_score:.0f}"
        arts = rep.execution_metadata.get("artifacts", {})
        exp.artifacts = [*(exp.artifacts or []),
                         *({"artifact_type": n, "artifact_location": m["location"], "artifact_hash": m["hash"]}
                           for n, m in arts.items())]
        self.registry.store.update_run(exp)


# ── helpers ───────────────────────────────────────────────────────────────────

def _extract_pm(execution_result):
    if hasattr(execution_result, "report") and execution_result.report is not None:
        return execution_result.report.metrics       # M8 ResearchSession
    if hasattr(execution_result, "metrics"):
        return execution_result.metrics               # BacktestReport
    if hasattr(execution_result, "daily_returns"):
        return execution_result                       # PerformanceMetrics
    raise ValueError("execution_result has no metrics / daily_returns")


def _timestamps(pm):
    curve = pm.equity_curve or []
    return [p.timestamp for p in curve][1:] if len(curve) > 1 else None


def _strip(d):
    """Drop heavy raw distributions before serialization (histograms live in visuals)."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = {kk: vv for kk, vv in v.items() if not isinstance(vv, np.ndarray)}
        else:
            out[k] = v
    return out


def _default_dir(execution_result, experiment) -> str:
    ac = getattr(getattr(execution_result, "config", None), "artifacts_dir", None)
    if ac:
        return ac
    key = getattr(experiment, "experiment_id", None) or "adhoc"
    return str(Path("./data/validation") / key)
