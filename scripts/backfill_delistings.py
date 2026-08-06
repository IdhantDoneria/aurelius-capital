"""Backfill delisting events (AIDP Phase 4).

Vendor-agnostic: reads a CSV of delisting records and appends them to the store,
carrying vendor/source metadata. No vendor is hardcoded — point it at any source
(SEC EDGAR company history export, a Yahoo inactive-ticker dump, a manual sheet)
that maps to the columns below. Optionally applies effective dates into
SecurityMaster so universe_as_of reflects them.

CSV columns (header required):
    security_id, effective_date, delisting_type[, event_date, reason,
    last_trade_date, exchange, source, vendor]

Usage:
    python scripts/backfill_delistings.py --file delistings.csv --vendor sharadar \
        --apply --identity-db data/identity.duckdb
"""

from __future__ import annotations

import argparse
import csv
from datetime import date

from aurelius.market_data.delistings import DelistingEvent, DelistingStore


def _d(s: str | None) -> date | None:
    s = (s or "").strip()
    return date.fromisoformat(s) if s else None


def load_csv(path: str, default_vendor: str | None) -> list[DelistingEvent]:
    events: list[DelistingEvent] = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            events.append(DelistingEvent(
                security_id=row["security_id"].strip(),
                effective_date=_d(row["effective_date"]),
                delisting_type=(row.get("delisting_type") or "UNKNOWN").strip().upper(),
                event_date=_d(row.get("event_date")),
                reason=(row.get("reason") or None),
                last_trade_date=_d(row.get("last_trade_date")),
                exchange=(row.get("exchange") or None),
                source=(row.get("source") or path),
                vendor=(row.get("vendor") or default_vendor),
            ))
    return events


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--file", required=True, help="CSV of delisting records")
    p.add_argument("--db", default="./data/delistings.duckdb")
    p.add_argument("--vendor", default=None, help="default vendor if CSV omits it")
    p.add_argument("--apply", action="store_true", help="push effective dates into SecurityMaster")
    p.add_argument("--identity-db", default="./data/identity.duckdb")
    args = p.parse_args()

    events = load_csv(args.file, args.vendor)
    store = DelistingStore(args.db)
    try:
        for ev in events:
            store.record(ev)
        applied = 0
        if args.apply:
            from aurelius.market_data.identity import SecurityMaster
            sm = SecurityMaster(args.identity_db)
            try:
                applied = store.apply_to_master(sm)
            finally:
                sm.close()
    finally:
        store.close()
    print(f"recorded {len(events)} delisting events; applied to master: {applied if args.apply else 0}")


if __name__ == "__main__":
    main()
