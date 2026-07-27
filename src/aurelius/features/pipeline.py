"""Feature pipeline — turns bar series into feature values, look-ahead safe.

Guarantees:
  - No look-ahead: the value for bar t is computed from a Window that contains
    only bars with timestamp <= t. Structurally enforced by slicing.
  - Batch: compute every registered feature for a whole symbol history.
  - Incremental: pass `since` to compute only newer timestamps; results are
    cached by (symbol, feature, version, timestamp) so re-runs skip work.
  - Missing data / insufficient history: value is None (not an error).
  - Per-feature error isolation: a raising feature yields None and is logged;
    it never aborts the batch.

Survivorship bias is the caller's responsibility: feed only the symbols that
were actually in the universe on each date. The pipeline never invents symbols.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import NamedTuple

from aurelius.core.logging import get_logger
from aurelius.features.registry import Bar, Feature, Window, all_features

logger = get_logger(__name__)


class FeatureValueRow(NamedTuple):
    symbol: str
    feature: str
    version: int
    timestamp: datetime
    value: Decimal | None


class FeaturePipeline:
    def __init__(
        self,
        features: Sequence[Feature] | None = None,
        use_cache: bool = True,
    ) -> None:
        self.features: list[Feature] = list(features) if features is not None else all_features()
        self._use_cache = use_cache
        self._cache: dict[tuple[str, str, int, datetime], Decimal | None] = {}
        # Bound the window so per-bar cost is O(max_lookback), not O(history).
        self._maxlen = max((f.spec.min_periods for f in self.features), default=1) + 1

    def compute_symbol(
        self,
        symbol: str,
        bars: Sequence[Bar],
        market: Sequence[Bar] | None = None,
        since: datetime | None = None,
    ) -> list[FeatureValueRow]:
        """Compute all features for one symbol's (ascending) bar history."""
        ordered = sorted(bars, key=lambda b: b.timestamp)
        market_close = self._align_market(ordered, market)

        opens = [b.open for b in ordered]
        highs = [b.high for b in ordered]
        lows = [b.low for b in ordered]
        closes = [b.close for b in ordered]
        vols = [b.volume for b in ordered]

        rows: list[FeatureValueRow] = []
        for i, bar in enumerate(ordered):
            if since is not None and bar.timestamp <= since:
                continue
            lo = max(0, i + 1 - self._maxlen)
            window = Window(
                open=opens[lo : i + 1],
                high=highs[lo : i + 1],
                low=lows[lo : i + 1],
                close=closes[lo : i + 1],
                volume=vols[lo : i + 1],
                market=market_close[lo : i + 1] if market_close is not None else None,
            )
            for feat in self.features:
                rows.append(self._one(symbol, feat, bar.timestamp, window))
        return rows

    def compute_batch(
        self,
        bars_by_symbol: dict[str, Sequence[Bar]],
        market: Sequence[Bar] | None = None,
        since: datetime | None = None,
    ) -> list[FeatureValueRow]:
        """Compute features for many symbols. `market` is the shared benchmark."""
        out: list[FeatureValueRow] = []
        for symbol, bars in bars_by_symbol.items():
            out.extend(self.compute_symbol(symbol, bars, market=market, since=since))
        return out

    # ── internals ──

    def _one(self, symbol: str, feat: Feature, ts: datetime, window: Window) -> FeatureValueRow:
        key = (symbol, feat.spec.name, feat.spec.version, ts)
        if self._use_cache and key in self._cache:
            return FeatureValueRow(symbol, feat.spec.name, feat.spec.version, ts, self._cache[key])

        if len(window) < feat.spec.min_periods:
            value: Decimal | None = None  # insufficient history — not an error
        else:
            try:
                value = feat(window)
            except Exception as exc:  # isolate a bad feature from the batch
                logger.warning(
                    "feature_error",
                    feature=feat.spec.key,
                    symbol=symbol,
                    ts=str(ts),
                    error=str(exc),
                )
                value = None

        if self._use_cache:
            self._cache[key] = value
        return FeatureValueRow(symbol, feat.spec.name, feat.spec.version, ts, value)

    @staticmethod
    def _align_market(bars: Sequence[Bar], market: Sequence[Bar] | None) -> list[Decimal] | None:
        """Align benchmark closes index-for-index with `bars` by timestamp.

        Returns None if no benchmark, or if it doesn't cover every bar timestamp
        (partial coverage would silently misalign returns — cross-asset features
        then correctly emit None instead of a wrong number).
        """
        if market is None:
            return None
        by_ts = {b.timestamp: b.close for b in market}
        aligned = [by_ts.get(b.timestamp) for b in bars]
        if any(c is None for c in aligned):
            return None
        return [c for c in aligned if c is not None]
