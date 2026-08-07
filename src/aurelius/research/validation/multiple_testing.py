"""Multiple-testing corrections (AIDP M9).

When many strategy variants are tested, the best in-sample p-value is optimistic.
Bonferroni and Holm control the family-wise error rate; Benjamini-Hochberg controls
the false discovery rate. Pure functions over a list of p-values.

References: Holm (1979); Benjamini & Hochberg (1995).
"""

from __future__ import annotations

import numpy as np


def bonferroni(pvalues, alpha: float = 0.05) -> dict:
    p = np.asarray(pvalues, dtype=float)
    m = p.size
    adj = np.minimum(p * m, 1.0)
    return {"method": "bonferroni", "adjusted": adj.tolist(),
            "reject": (adj <= alpha).tolist(), "alpha": alpha}


def holm(pvalues, alpha: float = 0.05) -> dict:
    p = np.asarray(pvalues, dtype=float)
    m = p.size
    order = np.argsort(p)
    adj = np.empty(m)
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (m - rank) * p[idx])
        adj[idx] = min(running, 1.0)
    return {"method": "holm", "adjusted": adj.tolist(),
            "reject": (adj <= alpha).tolist(), "alpha": alpha}


def benjamini_hochberg(pvalues, alpha: float = 0.05) -> dict:
    """BH FDR control. Returns adjusted p (q-values) and reject flags."""
    p = np.asarray(pvalues, dtype=float)
    m = p.size
    order = np.argsort(p)
    adj = np.empty(m)
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        idx = order[rank]
        prev = min(prev, p[idx] * m / (rank + 1))
        adj[idx] = prev
    return {"method": "benjamini_hochberg", "adjusted": adj.tolist(),
            "reject": (adj <= alpha).tolist(), "alpha": alpha}


def false_discovery_rate(pvalues, alpha: float = 0.05) -> float:
    """Estimated FDR at the BH threshold: (#rejected under null) / (#rejected)."""
    bh = benjamini_hochberg(pvalues, alpha)
    n_rej = sum(bh["reject"])
    return float(len(pvalues) * alpha / n_rej) if n_rej else 0.0
