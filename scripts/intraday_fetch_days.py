"""Fetch intraday bars one regular-trading-hours session at a time.

The shape of the request matters more than anything else here. Alpaca's
bars endpoint paginates with two caps at once -- roughly 900 bars *and*
roughly 30 symbols per page -- and asking for one symbol over one year hits
the bar cap on every page, so a page carries one symbol and the whole
universe costs about nine pages per symbol-year.

Asking instead for *one RTH session across the entire universe* hits the
symbol cap instead: about 34 symbols of a 26-bar session fit in a page, so a
day costs ~14 pages for 475 names. That is an order of magnitude fewer
requests for the same data, and it drops extended-hours bars for free
because the request window is the session itself.

The trading calendar is taken from the days the benchmark actually has a
daily bar, so holidays and half-days need no external calendar.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb
import pandas as pd
import requests

ROOT = Path("/Users/idhantdoneria/mentisrex-capital")
DATA = ROOT / "data" / "intraday"
URL = "https://data.alpaca.markets/v2/stocks/bars"

_SESSION = requests.Session()
_SESSION.mount("https://", requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=64))


class RateLimiter:
    """Token bucket shared across worker threads."""

    def __init__(self, per_minute: int) -> None:
        self.interval = 60.0 / max(per_minute, 1)
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = max(self._next - now, 0.0)
            self._next = max(self._next, now) + self.interval
        if wait > 0:
            time.sleep(wait)


LIMITER = RateLimiter(190)
_STATS = {"429": 0, "err": 0}


def creds() -> dict[str, str]:
    for line in (ROOT / ".env.development").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            import os

            os.environ.setdefault(k, v)
    import os

    return {
        "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_API_SECRET"],
    }


def session_window(day: pd.Timestamp) -> tuple[str, str]:
    """RTH bounds for `day` in UTC, honouring US daylight saving."""
    open_et = pd.Timestamp(f"{day.date()} 09:30", tz="America/New_York")
    close_et = pd.Timestamp(f"{day.date()} 16:00", tz="America/New_York")
    return (
        open_et.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
        close_et.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def fetch_day(day: pd.Timestamp, symbols: list[str], tf: str, headers) -> pd.DataFrame:
    start, end = session_window(day)
    rows: list[dict] = []
    token = None
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

        payload = None
        last: Exception | None = None
        for attempt in range(8):
            try:
                LIMITER.acquire()
                r = _SESSION.get(URL, params=params, headers=headers, timeout=120)
                if r.status_code == 429:
                    _STATS["429"] += 1
                    time.sleep(min(float(r.headers.get("Retry-After", 0)) or 2 ** attempt, 10))
                    last = RuntimeError("429")
                    continue
                r.raise_for_status()
                payload = r.json()
                break
            except Exception as exc:  # noqa: BLE001 - retried, then re-raised
                _STATS["err"] += 1
                last = exc
                time.sleep(min(2 ** attempt, 10))
        if payload is None:
            # Never fall through to "no more pages" on a failed request: that
            # is how a rate-limited shard silently becomes a truncated one.
            raise RuntimeError(f"exhausted retries for {day.date()}: {last}")

        for sym, bars in (payload.get("bars") or {}).items():
            for b in bars:
                rows.append(
                    {
                        "symbol": sym, "ts": b["t"], "open": b["o"], "high": b["h"],
                        "low": b["l"], "close": b["c"], "volume": b["v"],
                        "vwap": b.get("vw"), "trades": b.get("n"),
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


def trading_days(start: str, end: str, benchmark: str = "SPY") -> list[pd.Timestamp]:
    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT DISTINCT CAST(ts AT TIME ZONE 'America/New_York' AS DATE) AS d
        FROM parquet_scan('{DATA / 'daily' / '*.parquet'}')
        WHERE symbol = '{benchmark}' AND d BETWEEN DATE '{start}' AND DATE '{end}'
        ORDER BY d
        """
    ).fetchall()
    return [pd.Timestamp(r[0]) for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="15Min")
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-08-24")
    ap.add_argument("--out", default="bars_rth")
    ap.add_argument("--symbols-file", default=str(DATA / "intraday_symbols.txt"))
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--group-months", type=int, default=1, help="sessions per output shard")
    args = ap.parse_args()

    headers = creds()
    symbols = [s.strip() for s in Path(args.symbols_file).read_text().split() if s.strip()]
    days = trading_days(args.start, args.end)
    print(f"{len(symbols)} symbols, {len(days)} sessions, timeframe={args.timeframe}", flush=True)

    outdir = DATA / args.out
    outdir.mkdir(parents=True, exist_ok=True)

    # One shard per ISO week. Weeks rather than months so that an interrupted
    # run leaves usable data early and progress is visible within minutes
    # rather than half an hour.
    groups: dict[str, list[pd.Timestamp]] = {}
    for d in days:
        iso = d.isocalendar()
        groups.setdefault(f"{iso[0]}W{iso[1]:02d}", []).append(d)
    todo = [(k, v) for k, v in sorted(groups.items()) if not (outdir / f"{k}.parquet").exists()]
    print(f"{len(todo)} month-shards to fetch ({len(groups) - len(todo)} already present)", flush=True)

    t0 = time.time()
    done = 0
    total = 0
    lock = threading.Lock()

    def run(job):
        key, dd = job
        frames = [fetch_day(d, symbols, args.timeframe, headers) for d in dd]
        frames = [f for f in frames if len(f)]
        if not frames:
            (outdir / f"{key}.parquet").touch()
            return 0
        df = pd.concat(frames, ignore_index=True)
        tmp = outdir / f"{key}.parquet.tmp"
        df.to_parquet(tmp, index=False)
        tmp.rename(outdir / f"{key}.parquet")
        return len(df)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run, j): j[0] for j in todo}
        for f in as_completed(futs):
            key = futs[f]
            try:
                n = f.result()
            except Exception as exc:  # noqa: BLE001 - reported, shard left absent for resume
                print(f"FAILED {key}: {exc}", flush=True)
                n = 0
            with lock:
                done += 1
                total += n
                el = time.time() - t0
                print(
                    f"{done}/{len(todo)} {key} {total:,} bars {el:.0f}s "
                    f"eta {el / done * (len(todo) - done):.0f}s "
                    f"[429s={_STATS['429']} errs={_STATS['err']}]",
                    flush=True,
                )
    print(f"DONE {total:,} bars in {time.time() - t0:.0f}s -> {outdir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
