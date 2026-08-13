"""Maximum-diversification solver (AIDP M10).

Maximize the diversification ratio DR(w) = (wᵀσ) / √(wᵀΣw). The long-only optimum
satisfies w ∝ Σ⁻¹σ; we take that direction and let the constraint engine enforce
sign/bounds. σ are per-asset volatilities (√diag Σ).

Reference: Choueifaty & Coignard (2008) "Toward Maximum Diversification".
"""

from __future__ import annotations

import numpy as np

from mentisrex.research.portfolio.solvers.base import Solver, l1_normalize, pinv


class MaxDiversificationSolver(Solver):
    name = "max_diversification"

    def solve(self, mu, cov, *, ctx=None):
        sigma = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
        w = pinv(cov) @ sigma
        return l1_normalize(w)
