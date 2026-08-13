"""OpenBB provider adapter (AIDP M21).

Converts OpenBB-shaped records into M20 SourceMessage objects. OpenBB is an aggregation layer
that proxies many underlying sources (Yahoo, FRED, IMF, World Bank, ECB, etc.) behind a unified
schema. This adapter speaks that unified schema; it does NOT import openbb at module level so the
platform stays importable without OpenBB installed.

fetch() is a production contract that raises NotImplementedError. Use convert() offline with
pre-fetched OpenBB output for tests and research pipelines.
"""

from __future__ import annotations

from datetime import date, datetime

from mentisrex.research.market_data_ops.adapters import SourceAdapter, SourceMetadata
from mentisrex.research.market_data_ops.messages import (
    MessageType,
    SourceCapability,
    SourceMessage,
)


class OpenBBSourceAdapter(SourceAdapter):
    """Production contract wrapping OpenBB aggregated data.

    OpenBB equity records:  {symbol, date, open, high, low, close, volume, adj_close?, currency?}
    OpenBB macro records:   {date, value, series_id, unit?, source?}
    OpenBB FX records:      {date, base, quote, rate}
    """

    def __init__(self, *, name: str = "openbb") -> None:
        super().__init__(SourceMetadata(
            name,
            frozenset({
                SourceCapability.HISTORICAL,
                SourceCapability.BARS,
                SourceCapability.FUNDAMENTALS,
                SourceCapability.RATES,
                SourceCapability.FX,
            }),
            schema_version="1.0",
            description="OpenBB aggregated open-data adapter",
            vendor="openbb",
        ))
        self._seq = 0

    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[SourceMessage]:
        raise NotImplementedError(
            "openbb.fetch: no live session. Install openbb, fetch data externally, "
            "then call convert(records, as_of) to transform into SourceMessage objects."
        )

    def convert(self, records: list[dict], as_of: date) -> list[SourceMessage]:
        """Convert pre-fetched OpenBB records to SourceMessage (offline, testable)."""
        if self._state.value == "disconnected":
            self.connect()
        msgs = []
        for r in sorted(records, key=_sort_key):
            msg = self._one(r, as_of)
            if msg is not None:
                self._seq += 1
                msgs.append(_with_seq(msg, self._seq))
        return self._record(msgs)

    def _one(self, r: dict, as_of: date) -> SourceMessage | None:
        rec_date = _parse_date(r.get("date") or r.get("observation_date"))
        if rec_date is None:
            return None
        # PIT guard: reject records knowable after as_of
        if rec_date > as_of:
            return None

        # equity OHLCV record
        if "symbol" in r or ("close" in r and "open" in r):
            return self._equity_msg(r, rec_date)

        # macro / rate record
        if "series_id" in r or "value" in r:
            return self._macro_msg(r, rec_date)

        # FX record
        if "base" in r and "quote" in r:
            return self._fx_msg(r, rec_date)

        return None

    def _equity_msg(self, r: dict, rec_date: date) -> SourceMessage:
        symbol = str(r.get("symbol", r.get("id", "unknown")))
        payload: dict = {
            "id": symbol,
            "observation_date": rec_date.isoformat(),
            "effective_date": rec_date.isoformat(),
            "source": self.metadata.name,
        }
        if r.get("adj_close") is not None:
            payload.update({"field": "close", "type": "adjusted_close",
                            "value": float(r["adj_close"])})
        elif r.get("close") is not None:
            payload.update({"field": "close", "type": "close",
                            "value": float(r["close"])})
        if r.get("open") is not None:
            payload["open"] = float(r["open"])
        if r.get("high") is not None:
            payload["high"] = float(r["high"])
        if r.get("low") is not None:
            payload["low"] = float(r["low"])
        if r.get("volume") is not None:
            payload["volume"] = float(r["volume"])
        if r.get("currency"):
            payload["currency"] = str(r["currency"])
        payload.setdefault("field", "close")
        payload.setdefault("value", 0.0)
        return SourceMessage(
            source=self.metadata.name,
            payload=payload,
            msg_type=MessageType.OBSERVATION,
            vendor_id=symbol,
            observation_date=rec_date,
            effective_date=rec_date,
            schema_version=self.metadata.schema_version,
        )

    def _macro_msg(self, r: dict, rec_date: date) -> SourceMessage:
        series = str(r.get("series_id", r.get("id", "macro")))
        try:
            value = float(r.get("value", 0.0))
        except (TypeError, ValueError):
            return None
        payload = {
            "id": series,
            "field": series.lower(),
            "value": value,
            "observation_date": rec_date.isoformat(),
            "effective_date": rec_date.isoformat(),
            "unit": str(r.get("unit", "none")),
            "source": str(r.get("source", self.metadata.name)),
        }
        return SourceMessage(
            source=self.metadata.name,
            payload=payload,
            msg_type=MessageType.OBSERVATION,
            vendor_id=series,
            observation_date=rec_date,
            effective_date=rec_date,
            schema_version=self.metadata.schema_version,
        )

    def _fx_msg(self, r: dict, rec_date: date) -> SourceMessage:
        pair = f"{r['base']}/{r['quote']}"
        try:
            rate = float(r.get("rate", r.get("value", 0.0)))
        except (TypeError, ValueError):
            return None
        payload = {
            "id": pair,
            "field": "fx_rate",
            "type": "fx_rate",
            "value": rate,
            "base": str(r["base"]),
            "quote": str(r["quote"]),
            "observation_date": rec_date.isoformat(),
            "effective_date": rec_date.isoformat(),
            "source": self.metadata.name,
        }
        return SourceMessage(
            source=self.metadata.name,
            payload=payload,
            msg_type=MessageType.OBSERVATION,
            vendor_id=pair,
            observation_date=rec_date,
            effective_date=rec_date,
            schema_version=self.metadata.schema_version,
        )


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


def _sort_key(r: dict):
    return (str(r.get("date") or r.get("observation_date") or ""),
            str(r.get("symbol") or r.get("id") or r.get("series_id") or ""),
            str(r.get("field") or ""))


def _with_seq(msg: SourceMessage, seq: int) -> SourceMessage:
    from dataclasses import replace
    return replace(msg, sequence=seq)
