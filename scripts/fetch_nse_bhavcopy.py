"""Download NSE full bhavcopy for a given date (or today) and ingest into analytics.duckdb.

Uses jugaad-data (pip install jugaad-data). Full bhavcopy includes ISIN and
delivery data — strictly more useful than the plain bhavcopy. Each saved file
is also the mechanism for survivorship-free universe reconstruction: every symbol
that appeared in any day's bhavcopy was listed and trading that day.

Run daily after NSE close (~7 PM IST) to build a forward-survivorship-free archive.
Missed days are permanent gaps — set this up as a cron job.

Usage:
    python scripts/fetch_nse_bhavcopy.py                          # today
    python scripts/fetch_nse_bhavcopy.py --date 2026-08-14       # specific date
    python scripts/fetch_nse_bhavcopy.py --backfill-days 30       # last N trading days
    python scripts/fetch_nse_bhavcopy.py --no-ingest              # save CSV, skip DB write
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import date, timedelta
from pathlib import Path

_RAW_DIR = Path("./raw/nse_bhavcopy")
_STORE_DB = "./data/analytics.duckdb"


def _trading_days_back(n: int) -> list[date]:
    days = []
    d = date.today()
    while len(days) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri; NSE holidays not filtered here
            days.append(d)
    return list(reversed(days))


def download_bhavcopy(for_date: date, out_dir: Path) -> Path | None:
    try:
        from jugaad_data.nse import full_bhavcopy_save
    except ImportError:
        print("ERROR: jugaad-data not installed. Run: pip install jugaad-data", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        full_bhavcopy_save(for_date, str(out_dir))
        # jugaad_data saves as NSE_FO_BHAVCOPY_<date>.csv or similar; find it
        candidates = sorted(out_dir.glob(f"*{for_date.strftime('%d%m%Y')}*.csv"))
        if not candidates:
            # fallback: any CSV modified in the last minute
            candidates = sorted(out_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"  {for_date}: download failed — {exc}")
        return None


def ingest_csv(csv_path: Path, for_date: date, db_path: str) -> int:
    """Parse NSE bhavcopy CSV and write to DuckDB store keyed by ISIN."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from mentisrex.market_data.storage.duckdb_store import DuckDBStore

    rows: list[dict] = []
    with open(csv_path, newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            isin = (r.get("ISIN") or r.get("isin") or "").strip()
            symbol = (r.get("SYMBOL") or r.get("symbol") or "").strip()
            if not symbol:
                continue
            # Use ISIN as symbol key when available — permanent across renames
            key = isin if isin else f"NSE:{symbol}"
            try:
                rows.append({
                    "symbol": key,
                    "timestamp": for_date,
                    "frequency": "1d",
                    "open": float(r.get("OPEN") or r.get("open") or 0),
                    "high": float(r.get("HIGH") or r.get("high") or 0),
                    "low": float(r.get("LOW") or r.get("low") or 0),
                    "close": float(r.get("CLOSE") or r.get("close") or 0),
                    "volume": int(float(r.get("TOTTRDQTY") or r.get("volume") or 0)),
                    "vwap": None,
                    "trade_count": None,
                    "quality_score": None,
                    "source": "nse_bhavcopy",
                })
            except (TypeError, ValueError):
                continue

    if not rows:
        return 0
    store = DuckDBStore(db_path)
    try:
        return store.write_bars(rows)
    finally:
        store.close()


def process_date(for_date: date, *, ingest: bool, db_path: str) -> None:
    print(f"  {for_date} ...", end=" ", flush=True)
    # check cache first
    cached = sorted(_RAW_DIR.glob(f"*{for_date.strftime('%d%m%Y')}*.csv"))
    if cached:
        csv_path = cached[0]
        print(f"cached ({csv_path.name})", end=" ")
    else:
        csv_path = download_bhavcopy(for_date, _RAW_DIR)
        if csv_path is None:
            print("SKIP (no data)")
            return
        print(f"downloaded ({csv_path.name})", end=" ")

    if ingest:
        n = ingest_csv(csv_path, for_date, db_path)
        print(f"→ {n} bars ingested")
    else:
        print("(ingest skipped)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--date", help="specific date YYYY-MM-DD (default: today)")
    p.add_argument("--backfill-days", type=int, default=0,
                   help="download last N trading days instead of a single date")
    p.add_argument("--no-ingest", action="store_true", help="save CSV but skip DB write")
    p.add_argument("--db", default=_STORE_DB)
    args = p.parse_args()

    ingest = not args.no_ingest

    if args.backfill_days > 0:
        dates = _trading_days_back(args.backfill_days)
    elif args.date:
        dates = [date.fromisoformat(args.date)]
    else:
        dates = [date.today()]

    print(f"Processing {len(dates)} date(s)...")
    for d in dates:
        process_date(d, ingest=ingest, db_path=args.db)
        time.sleep(0.5)  # be polite to NSE


if __name__ == "__main__":
    main()
