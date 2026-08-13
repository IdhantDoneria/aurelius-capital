"""CSV file loader for historical market data.

Supports common CSV layouts:
  - With 'symbol' column: multi-symbol files
  - Without 'symbol' column: pass default_symbol to load_file()
  - Common timestamp formats: ISO 8601, YYYY-MM-DD, MM/DD/YYYY

Column name matching is case-insensitive and supports common aliases
(e.g. 'adj close', 'adjusted_close', 'c' all map to 'close').

Does NOT extend MarketDataAdapter — CSV is a batch load, not a historical
fetch with symbol + date range parameters. Use IngestionService.ingest_csv().
"""

import csv
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from mentisrex.core.errors import MarketDataError
from mentisrex.core.logging import get_logger
from mentisrex.market_data.adapters.base import RawBar

logger = get_logger(__name__)

_COLUMN_ALIASES: dict[str, list[str]] = {
    "symbol": ["symbol", "ticker"],
    "timestamp": ["timestamp", "date", "datetime", "time"],
    "open": ["open", "o"],
    "high": ["high", "h"],
    "low": ["low", "l"],
    "close": ["close", "c", "adj close", "adjusted_close"],
    "volume": ["volume", "vol", "v"],
    "vwap": ["vwap"],
    "trade_count": ["trade_count", "trades", "n"],
}

_TS_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d/%m/%Y",
]


def _parse_timestamp(raw: str) -> datetime:
    for fmt in _TS_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse timestamp: {raw!r}")


def _resolve_columns(headers: list[str]) -> dict[str, str]:
    """Map field names to actual CSV column names (case-insensitive)."""
    lower = {h.lower().strip(): h for h in headers}
    resolved: dict[str, str] = {}
    for field_name, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower:
                resolved[field_name] = lower[alias]
                break
    return resolved


class CSVLoader:
    """Parse CSV files into RawBar lists."""

    def load_file(
        self,
        file_path: Path,
        default_symbol: str | None = None,
        frequency: str = "1d",
    ) -> list[RawBar]:
        """Parse a CSV file.

        file_path: must exist and be readable
        default_symbol: used when CSV has no 'symbol' column
        frequency: cannot be inferred from CSV — caller must provide
        """
        if not file_path.exists():
            raise MarketDataError(f"CSV file not found: {file_path}")

        bars: list[RawBar] = []
        parse_errors: list[str] = []

        with file_path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise MarketDataError(f"CSV is empty or has no header: {file_path}")

            col = _resolve_columns(list(reader.fieldnames))

            required = {"timestamp", "open", "high", "low", "close", "volume"}
            missing = required - set(col)
            if missing:
                raise MarketDataError(
                    f"CSV missing required columns: {missing}. Found: {list(reader.fieldnames)}"
                )

            for line_num, row in enumerate(reader, start=2):
                try:
                    symbol = (
                        row[col["symbol"]].strip().upper()
                        if "symbol" in col
                        else (default_symbol or "").upper()
                    )
                    if not symbol:
                        parse_errors.append(
                            f"Line {line_num}: no symbol"
                            " (no 'symbol' column and default_symbol not set)"
                        )
                        continue

                    try:
                        ts = _parse_timestamp(row[col["timestamp"]].strip())
                    except ValueError as exc:
                        parse_errors.append(f"Line {line_num}: {exc}")
                        continue

                    def _dec(key: str, _row: dict = row, _col: dict = col) -> Decimal | None:
                        raw = _row.get(_col.get(key, ""), "").strip()
                        if not raw:
                            return None
                        try:
                            return Decimal(raw)
                        except InvalidOperation:
                            return None

                    open_ = _dec("open")
                    high_ = _dec("high")
                    low_ = _dec("low")
                    close_ = _dec("close")
                    volume_ = _dec("volume")

                    if None in (open_, high_, low_, close_, volume_):
                        parse_errors.append(f"Line {line_num}: non-numeric OHLCV value")
                        continue

                    tc_raw = _dec("trade_count")
                    bars.append(
                        RawBar(
                            symbol=symbol,
                            timestamp=ts,
                            open=open_,  # type: ignore[arg-type]
                            high=high_,  # type: ignore[arg-type]
                            low=low_,  # type: ignore[arg-type]
                            close=close_,  # type: ignore[arg-type]
                            volume=volume_,  # type: ignore[arg-type]
                            vwap=_dec("vwap"),
                            trade_count=int(tc_raw) if tc_raw is not None else None,
                            frequency=frequency,
                            source="csv",
                        )
                    )
                except Exception as exc:
                    parse_errors.append(f"Line {line_num}: unexpected error: {exc}")

        if parse_errors:
            logger.warning(
                "csv_parse_errors",
                file=str(file_path),
                error_count=len(parse_errors),
                sample=parse_errors[:5],
            )

        logger.info(
            "csv_load_complete", file=str(file_path), bar_count=len(bars), errors=len(parse_errors)
        )
        return bars
