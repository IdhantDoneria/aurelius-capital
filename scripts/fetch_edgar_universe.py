"""Build a CIK universe from SEC EDGAR for use with backfill_fundamentals.py.

Two modes:
  --tickers-only  (default): fetch company_tickers.json → write cik_list.txt.
                  Fast (~1 request). Current filers only — no delisted names.
  --with-delistings: also pull the submissions JSON per CIK to detect Form 15
                  (deregistration) filings. Writes a delistings CSV loadable by
                  backfill_delistings.py. Slow — one extra request per CIK.

SEC requires a descriptive User-Agent on every request.

Usage:
    python scripts/fetch_edgar_universe.py \\
        --user-agent "Mentisrex Research you@example.com" \\
        --out cik_list.txt

    python scripts/fetch_edgar_universe.py \\
        --user-agent "Mentisrex Research you@example.com" \\
        --with-delistings \\
        --delistings-out data/edgar_delistings.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import httpx

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_CACHE_DIR = Path("./raw/edgar")


def _headers(user_agent: str) -> dict:
    return {"User-Agent": user_agent}


def fetch_tickers(user_agent: str) -> dict:
    r = httpx.get(_TICKERS_URL, headers=_headers(user_agent), timeout=30.0)
    r.raise_for_status()
    return r.json()


def fetch_submissions(cik: int, user_agent: str) -> dict:
    cache = _CACHE_DIR / f"submissions_{cik:010d}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    r = httpx.get(_SUBMISSIONS_URL.format(cik=cik), headers=_headers(user_agent), timeout=30.0)
    r.raise_for_status()
    doc = r.json()
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(doc))
    return doc


def _detect_form15(submissions: dict) -> str | None:
    """Return the filing date of the first Form 15 found, or None."""
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    for form, date in zip(forms, dates):
        if str(form).startswith("15"):
            return date
    former_names = submissions.get("formerNames", [])
    return None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--user-agent", required=True, help='SEC requires "Name email"')
    p.add_argument("--out", default="cik_list.txt", help="output CIK list file")
    p.add_argument("--with-delistings", action="store_true",
                   help="pull submissions JSON per CIK to detect Form 15 delistings")
    p.add_argument("--delistings-out", default="data/edgar_delistings.csv",
                   help="output CSV for backfill_delistings.py")
    args = p.parse_args()

    print("Fetching company_tickers.json from SEC EDGAR...")
    tickers = fetch_tickers(args.user_agent)

    ciks = []
    ticker_map: dict[int, dict] = {}
    for entry in tickers.values():
        cik = int(entry["cik_str"])
        ciks.append(cik)
        ticker_map[cik] = entry

    Path(args.out).write_text("\n".join(str(c) for c in sorted(ciks)))
    print(f"Written {len(ciks)} CIKs to {args.out}")

    if not args.with_delistings:
        return

    print(f"Pulling submissions for {len(ciks)} CIKs to detect Form 15 delistings...")
    delistings: list[dict] = []
    for i, cik in enumerate(ciks):
        try:
            subs = fetch_submissions(cik, args.user_agent)
            form15_date = _detect_form15(subs)
            name = subs.get("name", ticker_map.get(cik, {}).get("title", ""))
            ticker = ticker_map.get(cik, {}).get("ticker", "")
            if form15_date:
                delistings.append({
                    "security_id": f"CIK{cik:010d}",
                    "effective_date": form15_date,
                    "delisting_type": "EXCHANGE_DELIST",
                    "event_date": form15_date,
                    "reason": "Form 15 deregistration",
                    "last_trade_date": "",
                    "exchange": subs.get("exchanges", [""])[0] if subs.get("exchanges") else "",
                    "source": "sec_edgar_form15",
                    "vendor": "sec_edgar",
                })
            time.sleep(0.12)  # SEC fair-access: keep under ~10 req/s
        except Exception as exc:  # noqa: BLE001
            print(f"  CIK {cik}: {exc}")
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(ciks)} processed, {len(delistings)} Form 15s found so far")

    Path(args.delistings_out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.delistings_out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "security_id", "effective_date", "delisting_type", "event_date",
            "reason", "last_trade_date", "exchange", "source", "vendor",
        ])
        writer.writeheader()
        writer.writerows(delistings)
    print(f"Written {len(delistings)} Form 15 delistings to {args.delistings_out}")
    print(f"Load into store: python scripts/backfill_delistings.py --file {args.delistings_out} --vendor sec_edgar")


if __name__ == "__main__":
    main()
