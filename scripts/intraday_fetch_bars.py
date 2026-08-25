"""Threaded Alpaca SIP bar downloader -> partitioned Parquet.

Used twice in the swing-programme build:
  1. `--timeframe 1Day` over the full asset list, to build a point-in-time
     liquidity universe that includes since-delisted names.
  2. `--timeframe 5Min` over just the universe members, to build the
     intraday feature panel.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

ROOT = Path("/Users/idhantdoneria/mentisrex-capital")
OUT = ROOT / "data" / "intraday"
URL = "https://data.alpaca.markets/v2/stocks/bars"

_local = threading.local()


def creds() -> dict[str, str]:
    for line in (ROOT / ".env.development").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)
    return {
        "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_API_SECRET"],
    }


def session() -> requests.Session:
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.mount("https://", requests.adapters.HTTPAdapter(pool_maxsize=8))
        _local.s = s
    return s


def fetch_chunk(symbols: list[str], tf: str, start: str, end: str, headers) -> pd.DataFrame:
    rows: list[dict] = []
    token = None
    s = session()
    while True:
        params = {
            "symbols": ",".join(symbols),
            "timeframe": tf,
            "start": start,
            "end": end,
            "limit": 10000,
            "feed": "sip",
            "adjustment": "all",
            "sort": "asc",
        }
        if token:
            params["page_token"] = token
        for attempt in range(6):
            try:
                r = s.get(URL, params=params, headers=headers, timeout=120)
                if r.status_code == 429:
                    time.sleep(2 * (attempt + 1))
                    continue
                r.raise_for_status()
                break
            except Exception:
                if attempt == 5:
                    raise
                time.sleep(2 * (attempt + 1))
        payload = r.json()
        for sym, bars in (payload.get("bars") or {}).items():
            for b in bars:
                rows.append(
                    {
                        "symbol": sym,
                        "ts": b["t"],
                        "open": b["o"],
                        "high": b["h"],
                        "low": b["l"],
                        "close": b["c"],
                        "volume": b["v"],
                        "vwap": b.get("vw"),
                        "trades": b.get("n"),
                    }
                )
        token = payload.get("next_page_token")
        if not token:
            break
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="1Day")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-08-24")
    ap.add_argument("--out", required=True, help="subdirectory name under data/intraday")
    ap.add_argument("--symbols-file", default=None, help="newline-delimited symbols; default = all assets")
    ap.add_argument("--chunk", type=int, default=40)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--year-split", action="store_true", help="split each chunk by calendar year")
    args = ap.parse_args()

    headers = creds()
    if args.symbols_file:
        symbols = [s.strip() for s in Path(args.symbols_file).read_text().split() if s.strip()]
    else:
        symbols = sorted(pd.read_parquet(OUT / "assets.parquet")["symbol"].tolist())
    print(f"{len(symbols)} symbols, timeframe={args.timeframe}")

    outdir = OUT / args.out
    outdir.mkdir(parents=True, exist_ok=True)

    chunks = [symbols[i : i + args.chunk] for i in range(0, len(symbols), args.chunk)]
    jobs: list[tuple[int, list[str], str, str]] = []
    if args.year_split:
        years = pd.date_range(args.start, args.end, freq="YS").strftime("%Y-%m-%d").tolist()
        bounds = sorted(set([args.start] + years + [args.end]))
        for ci, c in enumerate(chunks):
            for a, b in zip(bounds[:-1], bounds[1:]):
                jobs.append((ci, c, a, b))
    else:
        for ci, c in enumerate(chunks):
            jobs.append((ci, c, args.start, args.end))

    print(f"{len(jobs)} jobs")
    t0 = time.time()
    done = 0
    total_rows = 0
    lock = threading.Lock()

    def run(job):
        ci, c, a, b = job
        df = fetch_chunk(c, args.timeframe, a, b, headers)
        if len(df):
            tag = f"c{ci:04d}_{a}_{b}"
            df.to_parquet(outdir / f"{tag}.parquet", index=False)
        return len(df)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(run, j) for j in jobs]
        for f in as_completed(futs):
            n = f.result()
            with lock:
                done += 1
                total_rows += n
                if done % 25 == 0 or done == len(jobs):
                    el = time.time() - t0
                    print(
                        f"{done}/{len(jobs)} jobs  {total_rows:,} rows  "
                        f"{el:.0f}s  eta {el / done * (len(jobs) - done):.0f}s",
                        flush=True,
                    )
    print(f"DONE {total_rows:,} rows in {time.time() - t0:.0f}s -> {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
