"""Download the current NSE F&O-eligible securities list and store it as a dated CSV.

NSE publishes this under Market Data → Equity Derivatives on nseindia.com.
This script fetches the current list and appends a dated snapshot to
data/fo_eligibility_log.csv, which is your point-in-time F&O eligibility record.

Historical eligibility changes (pre-today) cannot be reconstructed automatically —
they must be manually sourced from press archives (Business Standard, Mint,
Moneycontrol). See docs/DATA_ACQUISITION_BRIEF.md §4.

Usage:
    python scripts/fetch_fo_eligible.py               # fetch today's list
    python scripts/fetch_fo_eligible.py --show-only   # print list, don't write
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

import httpx

# NSE API endpoint for F&O securities list (equity derivatives underlying)
_FO_URL = "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/market-data/securities-in-f-o",
}
_LOG_PATH = Path("data/fo_eligibility_log.csv")
_LOG_FIELDS = ["as_of_date", "symbol", "isin", "company_name"]


def fetch_fo_list() -> list[dict]:
    """Fetch current F&O eligible list from NSE API.

    NSE requires a Referer header and cookies from a homepage GET before hitting
    the API — this mimics that pattern without a browser.
    """
    with httpx.Client(headers=_HEADERS, timeout=30.0, follow_redirects=True) as client:
        # Prime cookies with a homepage visit
        client.get("https://www.nseindia.com")
        r = client.get(_FO_URL)
        r.raise_for_status()
    data = r.json()
    records = data.get("data", [])
    return [
        {
            "symbol": rec.get("symbol", ""),
            "isin": rec.get("meta", {}).get("isin", "") if isinstance(rec.get("meta"), dict) else "",
            "company_name": rec.get("meta", {}).get("companyName", "") if isinstance(rec.get("meta"), dict) else "",
        }
        for rec in records
        if rec.get("symbol")
    ]


def append_snapshot(records: list[dict], as_of: date) -> int:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not _LOG_PATH.exists()
    with open(_LOG_PATH, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_LOG_FIELDS)
        if write_header:
            writer.writeheader()
        for rec in records:
            writer.writerow({"as_of_date": as_of.isoformat(), **rec})
    return len(records)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--show-only", action="store_true", help="print list, don't write to CSV")
    args = p.parse_args()

    try:
        records = fetch_fo_list()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        print("NSE may be blocking — try during market hours or add a delay.", file=sys.stderr)
        sys.exit(1)

    if not records:
        print("No records returned — NSE response may have changed format.")
        sys.exit(1)

    if args.show_only:
        for rec in records:
            print(f"{rec['symbol']}\t{rec['isin']}\t{rec['company_name']}")
        print(f"\nTotal: {len(records)} F&O eligible securities")
        return

    today = date.today()
    n = append_snapshot(records, today)
    print(f"Appended {n} records for {today} to {_LOG_PATH}")
    print("Run daily to build a point-in-time F&O eligibility log.")
    print("NOTE: pre-today history requires manual sourcing from press archives.")


if __name__ == "__main__":
    main()
