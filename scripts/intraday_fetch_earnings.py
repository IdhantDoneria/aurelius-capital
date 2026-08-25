"""Download the historical Nasdaq earnings calendar -> Parquet.

Gives, per (date, symbol): reported EPS, consensus forecast, and surprise %.
Two uses downstream:
  * event gating  -- suppress liquidity-provision signals into a scheduled
    information event;
  * event alpha   -- the surprise is the conditioning variable for the
    gap-continuation sleeve.

`marketCap` in the payload is as-of-scrape, not point-in-time, so it is
dropped rather than stored.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

OUT = Path("/Users/idhantdoneria/mentisrex-capital/data/intraday")
H = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126 Safari/537.36"
    ),
    "Accept": "application/json",
}
_local = threading.local()


def sess() -> requests.Session:
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        _local.s = s
    return s


def one(day: str) -> list[dict]:
    for attempt in range(5):
        try:
            r = sess().get(
                "https://api.nasdaq.com/api/calendar/earnings",
                params={"date": day},
                headers=H,
                timeout=30,
            )
            if r.status_code != 200:
                time.sleep(1.5 * (attempt + 1))
                continue
            rows = (r.json().get("data") or {}).get("rows") or []
            return [
                {
                    "date": day,
                    "symbol": x.get("symbol"),
                    "eps": x.get("eps"),
                    "eps_forecast": x.get("epsForecast"),
                    "surprise_pct": x.get("surprise"),
                    "time": x.get("time"),
                    "n_estimates": x.get("noOfEsts"),
                    "fiscal_quarter": x.get("fiscalQuarterEnding"),
                }
                for x in rows
            ]
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-08-24")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    days = pd.bdate_range(args.start, args.end).strftime("%Y-%m-%d").tolist()
    print(f"{len(days)} weekdays")
    out: list[dict] = []
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(one, d): d for d in days}
        for f in as_completed(futs):
            out.extend(f.result())
            done += 1
            if done % 200 == 0:
                el = time.time() - t0
                print(f"{done}/{len(days)}  {len(out):,} rows  {el:.0f}s", flush=True)

    df = pd.DataFrame(out)
    df["date"] = pd.to_datetime(df["date"])

    def num(s, pct=False):
        s = s.astype(str).str.replace("$", "", regex=False).str.replace(",", "", regex=False)
        s = s.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
        return pd.to_numeric(s, errors="coerce")

    for c in ("eps", "eps_forecast", "surprise_pct", "n_estimates"):
        df[c] = num(df[c])
    df = df.dropna(subset=["symbol"]).drop_duplicates(subset=["date", "symbol"])
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT / "earnings.parquet", index=False)
    print(f"DONE {len(df):,} rows, {df['symbol'].nunique():,} symbols -> {OUT / 'earnings.parquet'}")
    print(df["date"].min(), df["date"].max())
    return 0


if __name__ == "__main__":
    sys.exit(main())
