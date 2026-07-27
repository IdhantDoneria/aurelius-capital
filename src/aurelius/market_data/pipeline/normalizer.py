"""Pure normalization functions. No I/O, no state — safe to unit test directly.

normalize_bar: canonicalize a RawBar (UTC timestamp, uppercase symbol, non-negative volume).
detect_gaps: identify missing bars in a time series.
compute_spike: flag bars that moved beyond a price threshold.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aurelius.market_data.adapters.base import RawBar


def to_utc(dt: datetime) -> datetime:
    """Convert naive datetime to UTC, or convert tz-aware to UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def normalize_bar(bar: RawBar) -> RawBar:
    """Canonicalize a RawBar from any source.

    - Symbol → uppercase, stripped
    - Timestamp → UTC
    - Volume → floor at 0 (some sources emit -1 for missing)
    """
    return RawBar(
        symbol=bar.symbol.upper().strip(),
        timestamp=to_utc(bar.timestamp),
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=max(bar.volume, Decimal("0")),
        frequency=bar.frequency,
        vwap=bar.vwap,
        trade_count=bar.trade_count,
        source=bar.source,
    )


def detect_gaps(bars: list[RawBar], max_gap_days: int = 5) -> list[datetime]:
    """Return timestamps *before* unexpected gaps in a sorted bar list.

    Normal weekend gaps (Fri→Mon = 3 calendar days) are not flagged.
    Gaps > max_gap_days are flagged — likely missing trading days or bad ingestion.

    bars must be sorted ascending by timestamp.
    """
    if len(bars) < 2:
        return []
    threshold = timedelta(days=max_gap_days)
    return [
        bars[i - 1].timestamp
        for i in range(1, len(bars))
        if bars[i].timestamp - bars[i - 1].timestamp > threshold
    ]


def compute_spike(bar: RawBar, prev_close: Decimal, threshold: Decimal = Decimal("0.20")) -> bool:
    """Return True if close moved more than threshold fraction vs prev_close.

    threshold=0.20 means >20% move. Used to flag potential bad ticks.
    Does not raise — callers decide whether to reject or just flag.
    """
    if prev_close <= 0:
        return False
    return abs(bar.close - prev_close) / prev_close > threshold
