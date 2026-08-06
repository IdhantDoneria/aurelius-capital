"""Survivorship audit (AIDP Phase 4).

Proves the historical universe differs from today's — the signature of a
survivorship-free dataset. Exits non-zero if they're equal, because equality
means dead companies were dropped and/or future listings leaked in (contamination).

Modes:
  --demo (default when no --identity-db): seeds Lehman (delisted 2008), Twitter
    (delisted 2022) and a 2025 IPO into in-memory stores and audits 2010 vs today.
  --identity-db PATH: audits the real SecurityMaster (+ --delistings-db).

Usage:
    python scripts/audit_survivorship.py
    python scripts/audit_survivorship.py --identity-db data/identity.duckdb \
        --delistings-db data/delistings.duckdb --as-of 2010-06-30
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from aurelius.market_data.delistings import DelistingEvent, DelistingStore
from aurelius.market_data.identity import Security, SecurityMaster, make_security_id
from aurelius.market_data.universe import UniverseEngine


def _seed_demo(sm: SecurityMaster, dl: DelistingStore) -> None:
    def reg(t, ex, first, isin):
        sid = make_security_id(isin=isin, figi=None, ticker=t, exchange=ex, first_date=first)
        sm.register(Security(security_id=sid, ticker=t, exchange=ex, isin=isin), valid_from=first)
        return sid

    reg("AAPL", "XNAS", date(1980, 12, 12), "US0378331005")           # survives
    leh = reg("LEH", "XNYS", date(1994, 1, 1), "US5249081002")        # bankrupt 2008 (pre-2010)
    sune = reg("SUNE", "XNYS", date(1995, 1, 1), "US86732Y1091")      # alive 2010, bankrupt 2016
    twtr = reg("TWTR", "XNYS", date(2013, 11, 7), "US90184L1026")     # delisted 2022
    reg("FUTR", "XNAS", date(2025, 1, 1), "US_FUTURE0001")            # future IPO
    dl.record(DelistingEvent(security_id=leh, effective_date=date(2008, 9, 15),
                             delisting_type="BANKRUPTCY", vendor="demo", source="audit"))
    dl.record(DelistingEvent(security_id=sune, effective_date=date(2016, 4, 21),
                             delisting_type="BANKRUPTCY", vendor="demo", source="audit"))
    dl.record(DelistingEvent(security_id=twtr, effective_date=date(2022, 11, 8),
                             delisting_type="ACQUISITION", vendor="demo", source="audit"))
    dl.apply_to_master(sm)


def audit(eng: UniverseEngine, as_of: date, today: date) -> int:
    hist = {s["security_id"] for s in eng.universe_as_of(as_of).securities}
    cur = {s["security_id"] for s in eng.universe_as_of(today).securities}
    disappeared = hist - cur          # alive then, gone now (survivorship victims)
    future_ipos = cur - hist          # exist now, didn't then

    print(f"as-of {as_of}:  {len(hist)} constituents")
    print(f"as-of {today} (current):  {len(cur)} constituents")
    print(f"disappeared since {as_of}: {len(disappeared)}  {sorted(disappeared)}")
    print(f"future listings excluded from {as_of}: {len(future_ipos)}  {sorted(future_ipos)}")

    if hist == cur:
        print("FAIL: historical universe == current universe → survivorship contamination")
        return 1
    print("PASS: historical universe differs from current — survivorship-free")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--identity-db")
    p.add_argument("--delistings-db", default="./data/delistings.duckdb")
    p.add_argument("--as-of", default="2010-06-30")
    args = p.parse_args()
    as_of = date.fromisoformat(args.as_of)
    today = date.today()

    if args.identity_db:
        sm = SecurityMaster(args.identity_db)
        dl = DelistingStore(args.delistings_db)
    else:
        sm = SecurityMaster(":memory:")
        dl = DelistingStore(":memory:")
        _seed_demo(sm, dl)

    try:
        rc = audit(UniverseEngine(sm, delisting_store=dl), as_of, today)
    finally:
        sm.close()
        dl.close()
    sys.exit(rc)


if __name__ == "__main__":
    main()
