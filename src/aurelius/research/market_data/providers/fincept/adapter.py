"""Fincept connector adapter (AIDP M21).

Fincept is an open-source financial data connector that unifies Yahoo Finance, SEC/EDGAR, FRED,
IMF, World Bank, data.gov.in, and NSE datasets. This adapter speaks Fincept's output format;
it does NOT import fincept at module level.

fetch() raises NotImplementedError. Use convert() with pre-fetched Fincept records offline.
Fincept records follow a common envelope: {symbol/id, date, field, value, source?, unit?}.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

from aurelius.research.market_data_ops.adapters import SourceAdapter, SourceMetadata
from aurelius.research.market_data_ops.messages import (
    MessageType,
    SourceCapability,
    SourceMessage,
)


class FinceptSourceAdapter(SourceAdapter):
    """Production contract wrapping Fincept connector output.

    Fincept normalises many underlying sources into a common dict schema:
        {id/symbol, date, field, value, source, unit?, currency?}
    That schema maps directly to SourceMessage.payload with minimal transformation.
    """

    def __init__(self, *, name: str = "fincept") -> None:
        super().__init__(SourceMetadata(
            name,
            frozenset({
                SourceCapability.HISTORICAL,
                SourceCapability.BARS,
                SourceCapability.FUNDAMENTALS,
                SourceCapability.RATES,
                SourceCapability.REFERENCE_DATA,
            }),
            schema_version="1.0",
            description="Fincept multi-source connector adapter",
            vendor="fincept",
        ))
        self._seq = 0

    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[SourceMessage]:
        raise NotImplementedError(
            "fincept.fetch: no live session. Install fincept, fetch data externally, "
            "then call convert(records, as_of) to transform into SourceMessage objects."
        )

    def convert(self, records: list[dict], as_of: date) -> list[SourceMessage]:
        """Convert pre-fetched Fincept records to SourceMessage (offline, testable)."""
        if self._state.value == "disconnected":
            self.connect()
        msgs = []
        for r in sorted(records, key=_sort_key):
            msg = self._one(r, as_of)
            if msg is not None:
                self._seq += 1
                msgs.append(replace(msg, sequence=self._seq))
        return self._record(msgs)

    def _one(self, r: dict, as_of: date) -> SourceMessage | None:
        rec_id = r.get("id") or r.get("symbol") or r.get("series_id")
        if rec_id is None:
            return None
        rec_date = _parse_date(r.get("date") or r.get("observation_date"))
        if rec_date is None or rec_date > as_of:
            return None
        field = str(r.get("field") or r.get("type") or "close")
        try:
            value = float(r.get("value", r.get(field, 0.0)))
        except (TypeError, ValueError):
            return None

        payload: dict = {
            "id": str(rec_id),
            "field": field,
            "value": value,
            "observation_date": rec_date.isoformat(),
            "effective_date": rec_date.isoformat(),
            "source": str(r.get("source", self.metadata.name)),
        }
        if r.get("unit"):
            payload["unit"] = str(r["unit"])
        if r.get("currency"):
            payload["currency"] = str(r["currency"])
        for extra in ("open", "high", "low", "close", "volume", "adj_close"):
            if r.get(extra) is not None:
                payload[extra] = float(r[extra])

        return SourceMessage(
            source=self.metadata.name,
            payload=payload,
            msg_type=MessageType.OBSERVATION,
            vendor_id=str(rec_id),
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
            str(r.get("id") or r.get("symbol") or r.get("series_id") or ""),
            str(r.get("field") or ""))
