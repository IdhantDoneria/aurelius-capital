"""Signal aggregation — combine many weak, noisy signals into one alpha per name.

The whole thesis of Phase 8: one signal is weak; a *diversified blend* of weakly
correlated signals has a higher information ratio. If K signals each have IR = r
and are mutually uncorrelated, the equal-weight blend has IR = r*sqrt(K) (the
"fundamental law of active management", breadth term). Correlation between
signals erodes that sqrt(K) toward 1.

Method:
  1. Per source, cross-sectionally standardize: z_{k,i} = (s_{k,i} - mean_k)/std_k.
     Puts momentum, mean-reversion, factor, ML scores on one comparable scale.
  2. Blend: alpha_i = sum_k w_k * z_{k,i}  (w_k default equal, sum to 1).

Assumptions:
  - Scores are cross-sectionally comparable after z-scoring (stationary x-section).
  - Sign convention: positive score = long conviction, negative = short.

Limitations / when it fails:
  - z-score assumes a meaningful cross-section (>= 2 names, non-zero dispersion).
    A single name, or all-equal scores, yields zero information (returns 0).
  - Highly correlated sources give no diversification — the sqrt(K) is a mirage.
  - Structural bias in one source (always positive) survives z-scoring only as
    relative rank; absolute mispricing is lost by design (this is intentional).
"""

from __future__ import annotations

import enum
import statistics
from dataclasses import dataclass


class SignalSource(enum.StrEnum):
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    FACTOR = "factor"
    ML = "ml"


@dataclass(frozen=True)
class RawSignal:
    """One source's raw view on one name. score sign = direction, |score| = conviction."""

    symbol: str
    source: SignalSource
    score: float


class SignalAggregator:
    def __init__(self, source_weights: dict[SignalSource, float] | None = None) -> None:
        self._weights = source_weights  # None -> equal weight across present sources

    def combine(self, signals: list[RawSignal]) -> dict[str, float]:
        """Return blended alpha per symbol. Cross-sectional z-score, then weight."""
        by_source: dict[SignalSource, list[RawSignal]] = {}
        for s in signals:
            by_source.setdefault(s.source, []).append(s)

        sources = list(by_source)
        if self._weights:
            total = sum(self._weights.get(src, 0.0) for src in sources) or 1.0
            wmap = {src: self._weights.get(src, 0.0) / total for src in sources}
        else:
            wmap = {src: 1.0 / len(sources) for src in sources}

        alpha: dict[str, float] = {}
        for src, group in by_source.items():
            for sym, z in self._zscore(group).items():
                alpha[sym] = alpha.get(sym, 0.0) + wmap[src] * z
        return alpha

    @staticmethod
    def _zscore(group: list[RawSignal]) -> dict[str, float]:
        scores = [g.score for g in group]
        if len(scores) < 2:
            return {g.symbol: 0.0 for g in group}   # no cross-section -> no info
        mean = statistics.mean(scores)
        sd = statistics.pstdev(scores)
        if sd == 0:
            return {g.symbol: 0.0 for g in group}   # no dispersion -> no info
        return {g.symbol: (g.score - mean) / sd for g in group}
