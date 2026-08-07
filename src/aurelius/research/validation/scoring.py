"""Research scoring engine (AIDP M9).

Seven component scores (0–100), each exposed separately, combined into a single
Research Score via configurable, documented weights. Also produces a confidence
decomposition (each component's contribution) so the final number is explainable.
"""

from __future__ import annotations

import math

# Default weights — sum to 1.0. Override via ValidationConfig.weights.
DEFAULT_WEIGHTS = {
    "statistical_validity": 0.25,
    "robustness": 0.20,
    "economic_significance": 0.15,
    "capacity": 0.10,
    "overfitting_risk": 0.15,     # higher score = LOWER overfitting risk
    "reproducibility": 0.10,
    "transparency": 0.05,
}


def _clip(x: float) -> float:
    return float(max(0.0, min(100.0, x)))


def _stat_score(summaries) -> float:
    sig = summaries.get("significance", {})
    p = sig.get("p_value", 1.0)
    dsr = summaries.get("overfitting", {}).get("dsr")
    perm = summaries.get("permutation", {}).get("p_value", 1.0)
    # p and permutation p small → high; blend with DSR probability
    s = 100.0 * (1 - min(p, 1.0)) ** 0.5
    s = 0.6 * s + 0.4 * 100.0 * (1 - min(perm, 1.0)) ** 0.5
    if dsr is not None and not math.isnan(dsr):
        s = 0.7 * s + 0.3 * 100.0 * dsr
    return _clip(s)


def _robustness_score(summaries) -> float:
    rob = summaries.get("robustness", {})
    pos = rob.get("rolling", {}).get("share_positive", 0.0)
    exp_pos = rob.get("expanding", {}).get("share_positive", 0.0)
    md = rob.get("missing_data", {})
    degr = md.get("max_degradation", 0.0)
    base = 100.0 * (0.6 * pos + 0.4 * exp_pos)
    base -= min(30.0, 100.0 * max(degr, 0.0))  # penalize fragility to dropped data
    return _clip(base)


def _econ_score(summaries) -> float:
    sr = summaries.get("significance", {}).get("sharpe", 0.0)
    # Sharpe 0→0, 1→~63, 2→~86, saturating
    return _clip(100.0 * (1 - math.exp(-max(sr, 0.0))))


def _capacity_score(summaries) -> float:
    cap = summaries.get("capacity", {})
    if cap.get("insufficient_data"):
        return 50.0
    util = cap.get("adv_utilisation")
    if util is None:
        return 60.0 if cap.get("capacity_signal") != "high_turnover" else 40.0
    return _clip(100.0 * (1 - min(util / 0.20, 1.0)))  # <20% ADV → full marks


def _overfit_score(summaries) -> float:
    of = summaries.get("overfitting", {})
    dsr = of.get("dsr")
    pbo = of.get("pbo")
    s = 60.0
    if dsr is not None and not math.isnan(dsr):
        s = 100.0 * dsr
    if pbo is not None:
        s = 0.5 * s + 0.5 * 100.0 * (1 - pbo)
    return _clip(s)


def _reproducibility_score(experiment) -> float:
    if experiment is None:
        return 0.0
    s = 0.0
    s += 40.0 if experiment.git_commit else 0.0
    dv = experiment.dataset_versions or {}
    s += 30.0 if dv.get("feature_registry_version") else 0.0
    s += 20.0 if experiment.random_seed is not None else 0.0
    s += 10.0 if experiment.fingerprint else 0.0
    return _clip(s)


def _transparency_score(summaries, experiment) -> float:
    s = 50.0
    if experiment and experiment.features:
        s += 20.0
    if experiment and experiment.artifacts:
        s += 20.0
    if summaries.get("factor", {}).get("market", {}).get("market_beta") is not None:
        s += 10.0
    return _clip(s)


def score(summaries: dict, experiment=None, *, weights: dict | None = None) -> dict:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    components = {
        "statistical_validity": _stat_score(summaries),
        "robustness": _robustness_score(summaries),
        "economic_significance": _econ_score(summaries),
        "capacity": _capacity_score(summaries),
        "overfitting_risk": _overfit_score(summaries),
        "reproducibility": _reproducibility_score(experiment),
        "transparency": _transparency_score(summaries, experiment),
    }
    total_w = sum(w[k] for k in components)
    research_score = sum(components[k] * w[k] for k in components) / total_w
    contributions = {k: components[k] * w[k] / total_w for k in components}
    return {
        "research_score": _clip(research_score),
        "components": components,
        "weights": {k: w[k] for k in components},
        "contributions": contributions,   # confidence decomposition
    }
