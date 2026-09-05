"""Yahoo Finance provider adapter (AIDP M21).

yfinance (>=0.2.40) is a declared project dependency, so this adapter can perform live fetches.
Tests use convert() with fixture dicts to stay network-free and deterministic.

Ticker → M19 IdentifierMap → internal security_id:
    pass an IdentifierMap to __init__; the adapter resolves each ticker PIT-aware. Without a map,
    ticker is used as the security_id (acceptable for research, wrong for production).

PIT safety:
    yfinance returns adjusted prices that incorporate splits/dividends applied retroactively.
    This adapter emits BOTH close (unadjusted) and adjusted_close when both are present, each as
    a distinct SourceMessage. Downstream normalization and PIT validation ensure adjusted prices
    are not used on dates before the adjustment was knowable.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

from mentisrex.research.market_data.identifiers import IdentifierMap, IdType
from mentisrex.research.market_data_ops.adapters import SourceAdapter, SourceMetadata
from mentisrex.research.market_data_ops.messages import (
    MessageType,
    SourceCapability,
    SourceMessage,
)


class YahooFinanceSourceAdapter(SourceAdapter):
    """Yahoo Finance adapter. convert() is fully offline; fetch() uses yfinance live."""

    def __init__(
        self,
        *,
        id_map: IdentifierMap | None = None,
        name: str = "yahoo_finance",
        timezone: str = "America/New_York",
    ) -> None:
        super().__init__(
            SourceMetadata(
                name,
                frozenset(
                    {
                        SourceCapability.HISTORICAL,
                        SourceCapability.BARS,
                        SourceCapability.CORPORATE_ACTIONS,
                    }
                ),
                schema_version="1.0",
                description="Yahoo Finance via yfinance — OHLCV + corporate actions",
                vendor="yahoo",
            )
        )
        self._id_map = id_map
        self._timezone = timezone
        self._seq = 0

    # ── production fetch (live, uses yfinance) ────────────────────────────────
    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[SourceMessage]:
        """Fetch from Yahoo Finance via yfinance. Requires yfinance installed and network access."""
        try:
            import yfinance as yf  # noqa: F401 — imported but result unused here
        except ImportError:
            raise NotImplementedError("yfinance not installed — pip install yfinance")
        if self._state.value == "disconnected":
            self.connect()
        tickers = list(security_ids or self._subscriptions)
        if not tickers:
            return []
        records = self._yfinance_fetch(tickers, as_of)
        return self.convert(records, as_of)

    def _yfinance_fetch(self, tickers: list, as_of: date) -> list[dict]:
        import yfinance as yf

        records = []
        for ticker in tickers:
            try:
                df = yf.Ticker(str(ticker)).history(
                    start="1990-01-01",
                    end=as_of.isoformat(),
                    auto_adjust=False,
                )
                if df.empty:
                    continue
                for row_date, row in df.iterrows():
                    d = row_date.date() if hasattr(row_date, "date") else row_date
                    records.append(
                        {
                            "symbol": str(ticker),
                            "date": d.isoformat(),
                            "open": float(row.get("Open", 0)),
                            "high": float(row.get("High", 0)),
                            "low": float(row.get("Low", 0)),
                            "close": float(row.get("Close", 0)),
                            "adj_close": float(row.get("Adj Close", row.get("Close", 0))),
                            "volume": float(row.get("Volume", 0)),
                            "dividends": float(row.get("Dividends", 0)),
                            "stock_splits": float(row.get("Stock Splits", 0)),
                        }
                    )
            except Exception:
                continue
        return records

    # ── offline conversion ────────────────────────────────────────────────────
    def convert(self, records: list[dict], as_of: date) -> list[SourceMessage]:
        """Convert Yahoo-shaped dicts to SourceMessage (offline, testable with fixtures)."""
        if self._state.value == "disconnected":
            self.connect()
        msgs = []
        for r in sorted(records, key=_sort_key):
            for msg in self._one(r, as_of):
                self._seq += 1
                msgs.append(replace(msg, sequence=self._seq))
        return self._record(msgs)

    def _one(self, r: dict, as_of: date) -> list[SourceMessage]:
        rec_date = _parse_date(r.get("date") or r.get("observation_date"))
        if rec_date is None or rec_date > as_of:
            return []
        ticker = str(r.get("symbol", r.get("id", "unknown")))
        sec_id = self._resolve(ticker, rec_date)

        out = []
        wire = {
            "source": self.metadata.name,
            "vendor_id": ticker,
            "observation_date": rec_date,
            "effective_date": rec_date,
            "schema_version": self.metadata.schema_version,
        }

        # unadjusted close
        if r.get("close") is not None:
            payload = {
                "id": sec_id,
                "field": "close",
                "type": "close",
                "value": float(r["close"]),
                "observation_date": rec_date.isoformat(),
                "effective_date": rec_date.isoformat(),
                "source": self.metadata.name,
            }
            _ohlcv(payload, r)
            out.append(SourceMessage(payload=payload, msg_type=MessageType.OBSERVATION, **wire))

        # adjusted close — separate message preserves provenance of adjustment
        if r.get("adj_close") is not None and r.get("adj_close") != r.get("close"):
            adj_payload = {
                "id": sec_id,
                "field": "close",
                "type": "adjusted_close",
                "value": float(r["adj_close"]),
                "observation_date": rec_date.isoformat(),
                "effective_date": rec_date.isoformat(),
                "source": self.metadata.name,
            }
            out.append(SourceMessage(payload=adj_payload, msg_type=MessageType.OBSERVATION, **wire))

        # dividends
        div = r.get("dividends", r.get("dividend", 0.0))
        if div and float(div) != 0.0:
            div_payload = {
                "id": sec_id,
                "field": "dividend",
                "type": "dividend",
                "value": float(div),
                "observation_date": rec_date.isoformat(),
                "effective_date": rec_date.isoformat(),
                "source": self.metadata.name,
            }
            out.append(SourceMessage(payload=div_payload, msg_type=MessageType.REFERENCE, **wire))

        # splits
        split = r.get("stock_splits", r.get("split_ratio", 0.0))
        if split and float(split) != 0.0 and float(split) != 1.0:
            split_payload = {
                "id": sec_id,
                "field": "split_ratio",
                "type": "split",
                "value": float(split),
                "observation_date": rec_date.isoformat(),
                "effective_date": rec_date.isoformat(),
                "source": self.metadata.name,
            }
            out.append(SourceMessage(payload=split_payload, msg_type=MessageType.REFERENCE, **wire))
        return out

    def _resolve(self, ticker: str, as_of: date) -> str:
        if self._id_map is None:
            return ticker
        try:
            return self._id_map.resolve(IdType.TICKER, ticker, as_of=as_of)
        except (KeyError, ValueError):
            return ticker  # fall back to ticker if map doesn't know it


def _ohlcv(payload: dict, r: dict) -> None:
    for f in ("open", "high", "low", "volume"):
        if r.get(f) is not None:
            payload[f] = float(r[f])


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
    return (
        str(r.get("date") or r.get("observation_date") or ""),
        str(r.get("symbol") or r.get("id") or ""),
    )
