"""India market data provider adapter (AIDP M21).

Supports NSE (National Stock Exchange), BSE (Bombay Stock Exchange), and data.gov.in macro data.
No live connectivity — convert() turns pre-fetched records into SourceMessage objects.

Identifier handling:
    NSE symbol  → IdType.EXCHANGE_TICKER (exchange="NSE")
    BSE code    → IdType.EXCHANGE_TICKER (exchange="BSE")
    ISIN        → IdType.ISIN
    All three → resolved through M19 IdentifierMap to internal security_id.

NSE OHLCV CSV format (bhav copy):
    SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,TOTALTRADES,ISIN

BSE OHLCV CSV format:
    Code,Name,Open,High,Low,Close,Volume,Date

data.gov.in macro format (varies):
    {indicator, date, value, unit?}
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

from mentisrex.research.market_data.identifiers import IdType, IdentifierMap
from mentisrex.research.market_data_ops.adapters import SourceAdapter, SourceMetadata
from mentisrex.research.market_data_ops.messages import (
    MessageType,
    SourceCapability,
    SourceMessage,
)


class IndiaSourceAdapter(SourceAdapter):
    """India market data adapter — NSE, BSE, data.gov.in. convert() is offline."""

    def __init__(self, *, id_map: IdentifierMap | None = None, name: str = "india") -> None:
        super().__init__(SourceMetadata(
            name,
            frozenset({
                SourceCapability.HISTORICAL,
                SourceCapability.BARS,
                SourceCapability.CORPORATE_ACTIONS,
                SourceCapability.REFERENCE_DATA,
            }),
            schema_version="1.0",
            description="India market data — NSE/BSE equities, corporate actions, data.gov.in",
            vendor="india",
        ))
        self._id_map = id_map
        self._seq = 0

    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[SourceMessage]:
        raise NotImplementedError(
            "india.fetch: download NSE bhav copy from nseindia.com or BSE bhavcopy, "
            "parse into records, then call convert_nse(records, as_of) or "
            "convert_bse(records, as_of)."
        )

    def convert_nse(self, records: list[dict], as_of: date) -> list[SourceMessage]:
        """Convert NSE bhav-copy records. Each record is one row of the NSE daily CSV."""
        if self._state.value == "disconnected":
            self.connect()
        msgs = []
        for r in sorted(records, key=lambda x: (str(x.get("TIMESTAMP") or x.get("date") or ""),
                                                  str(x.get("SYMBOL") or ""))):
            msg = self._nse_one(r, as_of)
            if msg is not None:
                self._seq += 1
                msgs.append(replace(msg, sequence=self._seq))
        return self._record(msgs)

    def convert_bse(self, records: list[dict], as_of: date) -> list[SourceMessage]:
        """Convert BSE bhavcopy records."""
        if self._state.value == "disconnected":
            self.connect()
        msgs = []
        for r in sorted(records, key=lambda x: (str(x.get("Date") or x.get("date") or ""),
                                                  str(x.get("Code") or x.get("code") or ""))):
            msg = self._bse_one(r, as_of)
            if msg is not None:
                self._seq += 1
                msgs.append(replace(msg, sequence=self._seq))
        return self._record(msgs)

    def convert_macro(self, records: list[dict], as_of: date) -> list[SourceMessage]:
        """Convert data.gov.in macro records: {indicator, date, value, unit?}."""
        if self._state.value == "disconnected":
            self.connect()
        msgs = []
        for r in sorted(records, key=lambda x: (str(x.get("date") or ""),
                                                  str(x.get("indicator") or ""))):
            msg = self._macro_one(r, as_of)
            if msg is not None:
                self._seq += 1
                msgs.append(replace(msg, sequence=self._seq))
        return self._record(msgs)

    def _nse_one(self, r: dict, as_of: date) -> SourceMessage | None:
        rec_date = _parse_date(r.get("TIMESTAMP") or r.get("date"))
        if rec_date is None or rec_date > as_of:
            return None
        symbol = str(r.get("SYMBOL") or r.get("symbol") or "").strip()
        isin = str(r.get("ISIN") or r.get("isin") or "").strip()
        if not symbol:
            return None
        sec_id = self._resolve_nse(symbol, isin, rec_date)
        try:
            close = float(r.get("CLOSE") or r.get("close") or 0.0)
        except (TypeError, ValueError):
            return None
        payload: dict = {
            "id": sec_id,
            "field": "close",
            "type": "close",
            "value": close,
            "observation_date": rec_date.isoformat(),
            "effective_date": rec_date.isoformat(),
            "currency": "INR",
            "source": self.metadata.name,
            "exchange": "NSE",
            "symbol": symbol,
        }
        if isin:
            payload["isin"] = isin
        for src, dst in (("OPEN", "open"), ("HIGH", "high"), ("LOW", "low"),
                          ("TOTTRDQTY", "volume"), ("TOTALTRADES", "total_trades")):
            if r.get(src) is not None:
                try:
                    payload[dst] = float(r[src])
                except (TypeError, ValueError):
                    pass
        return SourceMessage(
            source=self.metadata.name, payload=payload,
            msg_type=MessageType.OBSERVATION,
            vendor_id=f"NSE:{symbol}",
            observation_date=rec_date, effective_date=rec_date,
            schema_version=self.metadata.schema_version,
        )

    def _bse_one(self, r: dict, as_of: date) -> SourceMessage | None:
        raw_date = r.get("Date") or r.get("date")
        rec_date = _parse_date(raw_date)
        if rec_date is None or rec_date > as_of:
            return None
        bse_code = str(r.get("Code") or r.get("code") or "").strip()
        if not bse_code:
            return None
        sec_id = self._resolve_bse(bse_code, rec_date)
        try:
            close = float(r.get("Close") or r.get("close") or 0.0)
        except (TypeError, ValueError):
            return None
        payload: dict = {
            "id": sec_id,
            "field": "close",
            "type": "close",
            "value": close,
            "observation_date": rec_date.isoformat(),
            "effective_date": rec_date.isoformat(),
            "currency": "INR",
            "source": self.metadata.name,
            "exchange": "BSE",
            "bse_code": bse_code,
        }
        for src, dst in (("Open", "open"), ("High", "high"), ("Low", "low"), ("Volume", "volume")):
            if r.get(src) is not None:
                try:
                    payload[dst] = float(r[src])
                except (TypeError, ValueError):
                    pass
        return SourceMessage(
            source=self.metadata.name, payload=payload,
            msg_type=MessageType.OBSERVATION,
            vendor_id=f"BSE:{bse_code}",
            observation_date=rec_date, effective_date=rec_date,
            schema_version=self.metadata.schema_version,
        )

    def _macro_one(self, r: dict, as_of: date) -> SourceMessage | None:
        rec_date = _parse_date(r.get("date"))
        if rec_date is None or rec_date > as_of:
            return None
        indicator = str(r.get("indicator") or r.get("series_id") or "macro").strip()
        try:
            value = float(r.get("value", 0.0))
        except (TypeError, ValueError):
            return None
        payload: dict = {
            "id": indicator,
            "field": indicator.lower().replace(" ", "_"),
            "value": value,
            "observation_date": rec_date.isoformat(),
            "effective_date": rec_date.isoformat(),
            "source": self.metadata.name,
            "country": "IN",
        }
        if r.get("unit"):
            payload["unit"] = str(r["unit"])
        return SourceMessage(
            source=self.metadata.name, payload=payload,
            msg_type=MessageType.OBSERVATION,
            vendor_id=f"IN:{indicator}:{rec_date.isoformat()}",
            observation_date=rec_date, effective_date=rec_date,
            schema_version=self.metadata.schema_version,
        )

    def _resolve_nse(self, symbol: str, isin: str, as_of: date) -> str:
        if self._id_map is not None:
            if isin:
                try:
                    return self._id_map.resolve(IdType.ISIN, isin, as_of=as_of)
                except (KeyError, ValueError):
                    pass
            try:
                return self._id_map.resolve(IdType.EXCHANGE_TICKER, f"NSE:{symbol}", as_of=as_of)
            except (KeyError, ValueError):
                pass
        return f"NSE:{symbol}"

    def _resolve_bse(self, bse_code: str, as_of: date) -> str:
        if self._id_map is not None:
            try:
                return self._id_map.resolve(IdType.EXCHANGE_TICKER, f"BSE:{bse_code}", as_of=as_of)
            except (KeyError, ValueError):
                pass
        return f"BSE:{bse_code}"


def _parse_date(v) -> date | None:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%Y%m%d"):
            try:
                return datetime.strptime(v.strip(), fmt).date()
            except ValueError:
                continue
    return None
