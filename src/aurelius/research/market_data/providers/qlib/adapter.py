"""Qlib compatibility layer (AIDP M21).

Allows Aurelius datasets to interoperate with Qlib-style ML workflows. Qlib organises market data
as per-stock daily CSV files under a flat directory. This module provides:

    QlibExporter  — exports CanonicalObservation sequences to Qlib-compatible CSV structure
    QlibSourceAdapter — reads Qlib-format CSVs back into SourceMessage objects

Neither class imports qlib at module level. The export/import format is Qlib's disk layout only;
no Qlib portfolio engine, execution logic or training pipeline is used.

Qlib daily CSV format (per-stock):
    date,open,high,low,close,volume,factor,change
    2024-01-02,188.5,189.0,187.0,188.0,52345000,1.0,0.01

The 'factor' column is the cumulative adjustment factor (close_adj / close_raw).
"""

from __future__ import annotations

import csv
import io
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from aurelius.research.market_data_ops.adapters import SourceAdapter, SourceMetadata
from aurelius.research.market_data_ops.messages import (
    MessageType,
    SourceCapability,
    SourceMessage,
)


class QlibSourceAdapter(SourceAdapter):
    """Reads Qlib-format per-stock CSV files back into SourceMessage objects.

    fetch() raises NotImplementedError. Use convert_csv(csv_text, symbol, as_of) or
    convert_directory(path, as_of) for offline/testable conversion.
    """

    def __init__(self, *, name: str = "qlib") -> None:
        super().__init__(SourceMetadata(
            name,
            frozenset({SourceCapability.HISTORICAL, SourceCapability.BARS}),
            schema_version="1.0",
            description="Qlib-format OHLCV reader",
            vendor="qlib",
        ))
        self._seq = 0

    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[SourceMessage]:
        raise NotImplementedError(
            "qlib.fetch: point at a Qlib data directory and call "
            "convert_directory(path, as_of) instead."
        )

    def convert_csv(self, csv_text: str, symbol: str, as_of: date) -> list[SourceMessage]:
        """Convert Qlib-format CSV text for one stock to SourceMessage objects."""
        if self._state.value == "disconnected":
            self.connect()
        records = list(csv.DictReader(io.StringIO(csv_text.strip())))
        msgs = []
        for r in records:
            for msg in self._one(r, symbol, as_of):
                self._seq += 1
                msgs.append(replace(msg, sequence=self._seq))
        return self._record(msgs)

    def convert_directory(self, directory: str | Path, as_of: date,
                          *, symbols: list[str] | None = None) -> list[SourceMessage]:
        """Convert all CSV files in a Qlib data directory."""
        if self._state.value == "disconnected":
            self.connect()
        root = Path(directory)
        msgs = []
        for csv_file in sorted(root.glob("*.csv")):
            sym = csv_file.stem.upper()
            if symbols is not None and sym not in symbols:
                continue
            csv_msgs = self.convert_csv(csv_file.read_text(), sym, as_of)
            msgs.extend(csv_msgs)
        return msgs

    def _one(self, r: dict, symbol: str, as_of: date) -> list[SourceMessage]:
        rec_date = _parse_date(r.get("date"))
        if rec_date is None or rec_date > as_of:
            return []
        base = dict(
            source=self.metadata.name,
            msg_type=MessageType.OBSERVATION,
            vendor_id=symbol,
            observation_date=rec_date,
            effective_date=rec_date,
            schema_version=self.metadata.schema_version,
        )
        msgs = []
        try:
            close = float(r.get("close", 0.0))
        except (TypeError, ValueError):
            return []

        payload: dict = {
            "id": symbol, "field": "close", "type": "close",
            "value": close,
            "observation_date": rec_date.isoformat(),
            "effective_date": rec_date.isoformat(),
            "source": self.metadata.name,
        }
        for src, dst in (("open", "open"), ("high", "high"), ("low", "low"), ("volume", "volume")):
            if r.get(src) not in (None, ""):
                try:
                    payload[dst] = float(r[src])
                except (TypeError, ValueError):
                    pass

        msgs.append(SourceMessage(payload=payload, **base))

        # factor → adjusted close when present and ≠ 1
        factor_str = r.get("factor", "1.0")
        try:
            factor = float(factor_str) if factor_str not in (None, "") else 1.0
        except (TypeError, ValueError):
            factor = 1.0
        if factor != 1.0 and factor > 0:
            adj_payload = {
                "id": symbol, "field": "close", "type": "adjusted_close",
                "value": round(close * factor, 6),
                "observation_date": rec_date.isoformat(),
                "effective_date": rec_date.isoformat(),
                "source": self.metadata.name,
                "adjustment_factor": factor,
            }
            msgs.append(SourceMessage(payload=adj_payload, **base))

        return msgs


class QlibExporter:
    """Export CanonicalObservation sequences to Qlib-compatible per-stock CSV files.

    Does not depend on Qlib runtime — pure filesystem output.
    """

    def export(self, observations, output_dir: str | Path) -> dict[str, Path]:
        """Group observations by security_id and write one CSV per stock.

        Returns mapping of security_id → written file path.
        """
        from collections import defaultdict
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)

        # group by security_id
        by_stock: dict = defaultdict(list)
        for obs in observations:
            if obs.field in ("close", "open", "high", "low", "volume"):
                by_stock[obs.security_id].append(obs)

        written = {}
        for security_id, obs_list in sorted(by_stock.items()):
            # pivot: date → {field: value}
            by_date: dict = {}
            for obs in obs_list:
                d = obs.effective_date
                by_date.setdefault(d, {})[obs.field] = obs.value

            rows = []
            for d in sorted(by_date):
                row = by_date[d]
                rows.append({
                    "date": d.isoformat(),
                    "open": row.get("open", ""),
                    "high": row.get("high", ""),
                    "low": row.get("low", ""),
                    "close": row.get("close", ""),
                    "volume": row.get("volume", ""),
                    "factor": "1.0",
                    "change": "",
                })

            safe_name = security_id.replace("/", "_").replace(":", "_")
            out_path = root / f"{safe_name}.csv"
            with open(out_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["date", "open", "high", "low", "close",
                                                         "volume", "factor", "change"])
                writer.writeheader()
                writer.writerows(rows)
            written[security_id] = out_path

        return written


def _parse_date(v) -> date | None:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None
