"""FinanceToolkit-style adapter (AIDP M21).

Converts financial statement records into SourceMessage objects and routes them to the
analytics/fundamentals layer for ratio computation. The FinanceToolkit library itself is NOT
imported — this adapter works with the same dict-shaped financial records that FinanceToolkit
would produce, so it is usable with or without FinanceToolkit installed.

Input format (FinanceToolkit-style income statement record):
    {
      "symbol": "AAPL", "date": "2022-09-24",
      "revenue": 394328000000, "gross_profit": 170782000000,
      "operating_income": 119437000000, "net_income": 99803000000,
      "ebitda": 130541000000, "eps": 6.11, "eps_diluted": 6.11,
      "shares_outstanding": 16325819000, "currency": "USD"
    }

Balance sheet record:
    {
      "symbol": "AAPL", "date": "2022-09-24",
      "total_assets": 352755000000, "total_liabilities": 302083000000,
      "stockholders_equity": 50672000000, "cash": 23646000000,
      "current_assets": 135405000000, "current_liabilities": 153982000000,
      "long_term_debt": 98959000000
    }

fetch() raises NotImplementedError. Use convert(records, as_of) offline.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

from mentisrex.research.market_data_ops.adapters import SourceAdapter, SourceMetadata
from mentisrex.research.market_data_ops.messages import (
    MessageType,
    SourceCapability,
    SourceMessage,
)

# fields to emit as individual SourceMessage observations
_INCOME_FIELDS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "ebitda",
    "eps",
    "eps_diluted",
    "shares_outstanding",
    "rd_expense",
    "income_tax",
    "interest_expense",
    "total_expenses",
)
_BALANCE_FIELDS = (
    "total_assets",
    "current_assets",
    "cash",
    "total_liabilities",
    "current_liabilities",
    "long_term_debt",
    "stockholders_equity",
    "retained_earnings",
    "goodwill",
    "intangibles",
)
_CASHFLOW_FIELDS = (
    "cash_flow_operations",
    "cash_flow_investing",
    "cash_flow_financing",
    "capex",
    "free_cash_flow",
    "dividends_paid",
)
_ALL_FIELDS = frozenset(_INCOME_FIELDS + _BALANCE_FIELDS + _CASHFLOW_FIELDS)


class FinanceToolkitSourceAdapter(SourceAdapter):
    """Production contract wrapping FinanceToolkit-style financial records."""

    def __init__(self, *, name: str = "financetoolkit") -> None:
        super().__init__(
            SourceMetadata(
                name,
                frozenset({SourceCapability.HISTORICAL, SourceCapability.FUNDAMENTALS}),
                schema_version="1.0",
                description="FinanceToolkit-style financial statement adapter",
                vendor="financetoolkit",
            )
        )
        self._seq = 0

    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[SourceMessage]:
        raise NotImplementedError(
            "financetoolkit.fetch: use FinanceToolkit or another fundamental data source "
            "to fetch financial records, then call convert(records, as_of)."
        )

    def convert(self, records: list[dict], as_of: date) -> list[SourceMessage]:
        """Convert FinanceToolkit-style financial dicts to SourceMessage (offline)."""
        if self._state.value == "disconnected":
            self.connect()
        msgs = []
        for r in sorted(
            records,
            key=lambda x: (str(x.get("date") or ""), str(x.get("symbol") or x.get("id") or "")),
        ):
            for msg in self._one(r, as_of):
                self._seq += 1
                msgs.append(replace(msg, sequence=self._seq))
        return self._record(msgs)

    def _one(self, r: dict, as_of: date) -> list[SourceMessage]:
        rec_date = _parse_date(r.get("date") or r.get("period_end"))
        # PIT: filing/reporting date if present; else use period date (imprecise — research only)
        knowledge_date = _parse_date(r.get("filed") or r.get("filing_date")) or rec_date
        if rec_date is None or knowledge_date is None:
            return []
        if knowledge_date > as_of:
            return []
        symbol = str(r.get("symbol") or r.get("id") or "unknown")
        currency = str(r.get("currency", "USD"))
        base = {
            "source": self.metadata.name,
            "msg_type": MessageType.OBSERVATION,
            "vendor_id": symbol,
            "observation_date": knowledge_date,
            "effective_date": rec_date,
            "schema_version": self.metadata.schema_version,
        }
        msgs = []
        for field in _ALL_FIELDS:
            val = r.get(field)
            if val is None:
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            payload = {
                "id": symbol,
                "field": field,
                "value": fval,
                "observation_date": knowledge_date.isoformat(),
                "effective_date": rec_date.isoformat(),
                "source": self.metadata.name,
                "currency": currency,
            }
            msgs.append(SourceMessage(payload=payload, **base))
        return msgs


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
