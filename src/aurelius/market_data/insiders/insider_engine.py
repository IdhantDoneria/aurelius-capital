"""Insider research accessor (AIDP Phase 5).

Point-in-time insider signals composed over InsiderStore.transactions_as_of, so
every figure reflects only filings public by the query date. Optionally resolves
a ticker to a security_id through SecurityMaster (Phase 2) so identity changes
don't break historical lookups.

Signal focus: open-market purchases (code P) and sales (code S) — the
economically informative codes. Grants/exercises/tax (A/M/F) are excluded from
buy/sell pressure but remain queryable in the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

_BUY, _SELL = "P", "S"


@dataclass(frozen=True)
class InsiderSignal:
    security_id: str
    as_of: date | datetime
    purchases: int
    sales: int
    buy_value: float
    sell_value: float
    net_value: float
    insider_count: int          # distinct insiders buying (cluster size)
    ownership_change: float     # signed shares across available transactions
    cluster_buy: bool


class InsiderEngine:
    def __init__(self, store, *, security_master=None, cluster_threshold: int = 3) -> None:
        self._store = store
        self._sm = security_master
        self._cluster_threshold = cluster_threshold

    def resolve_security(self, ticker: str, as_of: date) -> str | None:
        if self._sm is None:
            return None
        return self._sm.resolve_as_of(ticker, as_of)

    def insider_signal_as_of(self, security_id: str, as_of: date | datetime) -> InsiderSignal:
        txns = self._store.transactions_as_of(security_id, as_of)
        buys = [t for t in txns if t["transaction_code"] == _BUY]
        sells = [t for t in txns if t["transaction_code"] == _SELL]
        buy_value = sum(t["value"] or 0.0 for t in buys)
        sell_value = sum(t["value"] or 0.0 for t in sells)
        buyers = {t["insider_name"] for t in buys if t["insider_name"]}
        ownership_change = sum(t["shares"] or 0.0 for t in txns if t["transaction_code"] in (_BUY, _SELL))
        return InsiderSignal(
            security_id=security_id, as_of=as_of,
            purchases=len(buys), sales=len(sells),
            buy_value=buy_value, sell_value=sell_value,
            net_value=buy_value - sell_value,
            insider_count=len(buyers),
            ownership_change=ownership_change,
            cluster_buy=len(buyers) >= self._cluster_threshold,
        )
