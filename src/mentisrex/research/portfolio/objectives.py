"""Optimization objectives (AIDP M10).

Each objective is a named contract with an explicit mathematical definition,
assumptions, and limitations — nothing hidden. The engine maps an Objective to a
solver; the maths lives in `solvers/`.
"""

from __future__ import annotations

import enum


class Objective(enum.StrEnum):
    EQUAL_WEIGHT = "equal_weight"
    MAX_SHARPE = "max_sharpe"
    MIN_VARIANCE = "min_variance"
    RISK_PARITY = "risk_parity"
    MAX_DIVERSIFICATION = "max_diversification"
    TRACKING_ERROR = "tracking_error"


# Documentation of each objective — surfaced in the portfolio metadata so the
# assumptions travel with the result.
DEFINITIONS: dict[str, dict] = {
    "equal_weight": {
        "definition": "w_i = 1/N (gross-normalized).",
        "assumptions": "no view on returns or risk; maximal prior ignorance.",
        "limitations": "ignores covariance and signal strength entirely.",
    },
    "max_sharpe": {
        "definition": "maximize (wᵀμ)/√(wᵀΣw); unconstrained optimum w ∝ Σ⁻¹μ.",
        "assumptions": "μ and Σ are accurate; returns ~ IID; single-period.",
        "limitations": "extremely sensitive to μ estimation error; concentrated.",
    },
    "min_variance": {
        "definition": "minimize wᵀΣw s.t. Σw=1; optimum w ∝ Σ⁻¹1.",
        "assumptions": "Σ accurate and invertible; ignores expected returns.",
        "limitations": "return-agnostic; loads low-vol names, can concentrate.",
    },
    "risk_parity": {
        "definition": "equalize risk contributions RC_i = w_i(Σw)_i ∀ i.",
        "assumptions": "risk = volatility; correlations stable.",
        "limitations": "no return view; iterative (no closed form under constraints).",
    },
    "max_diversification": {
        "definition": "maximize diversification ratio (wᵀσ)/√(wᵀΣw); w ∝ Σ⁻¹σ.",
        "assumptions": "σ are per-asset vols; Σ accurate.",
        "limitations": "return-agnostic; sensitive to Σ conditioning.",
    },
    "tracking_error": {
        "definition": "minimize active variance (w−b)ᵀΣ(w−b), optionally tilted by μ.",
        "assumptions": "benchmark weights b given; Σ accurate.",
        "limitations": "collapses to b without a return tilt; TE budget approximate.",
    },
}
