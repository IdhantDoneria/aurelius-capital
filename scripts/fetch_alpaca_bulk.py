"""Bulk-download daily bars from Alpaca for a universe of tickers.

Maps tickers to CIK-derived security_ids via the EDGAR company_tickers.json so
every stored bar keys against the same permanent ID from day one. Free tier serves
IEX feed (explicit): ~2.5% of consolidated volume — fine for daily bars.

Incremental: only requests bars from last_stored_date+1 to today per symbol.

Requires ALPACA_PAPER_API_KEY and ALPACA_PAPER_API_SECRET in env or --key/--secret.

Usage:
    python scripts/fetch_alpaca_bulk.py --tickers AAPL MSFT KO
    python scripts/fetch_alpaca_bulk.py --cik-tickers-json cik_tickers.json
    python scripts/fetch_alpaca_bulk.py --ticker-file tickers.txt --start 2018-01-01
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

_DATA_BASE = "https://data.alpaca.markets/v2"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_BATCH_SIZE = 50  # symbols per Alpaca multi-bar request
_DEFAULT_START = "2015-01-01"


def _alpaca_headers(key: str, secret: str) -> dict:
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def _edgar_ticker_to_cik(user_agent: str | None) -> dict[str, str]:
    """Return {TICKER_UPPER: "CIK0000..."} from EDGAR company_tickers.json."""
    cache = Path("./raw/edgar/company_tickers.json")
    if cache.exists():
        doc = json.loads(cache.read_text())
    else:
        if not user_agent:
            print("WARNING: no --edgar-user-agent; skipping CIK mapping (storing by ticker only)")
            return {}
        r = httpx.get(_TICKERS_URL, headers={"User-Agent": user_agent}, timeout=30.0)
        r.raise_for_status()
        doc = r.json()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(doc))
    return {v["ticker"].upper(): f"CIK{int(v['cik_str']):010d}" for v in doc.values()}


def _last_stored_date(db_path: str, security_id: str) -> date | None:
    try:
        import duckdb
        con = duckdb.connect(db_path, read_only=True)
        row = con.execute(
            "SELECT MAX(CAST(timestamp AS DATE)) FROM ohlcv WHERE symbol=?", [security_id]
        ).fetchone()
        con.close()
        if row and row[0]:
            return row[0]
    except Exception:  # noqa: BLE001
        pass
    return None


async def _fetch_bars(
    client: httpx.AsyncClient, symbol: str, start: str, end: str, headers: dict
) -> list[dict]:
    bars = []
    page_token = None
    while True:
        params: dict = {
            "start": start,
            "end": end,
            "timeframe": "1Day",
            "limit": 10_000,
            "adjustment": "all",
            "feed": "iex",
        }
        if page_token:
            params["page_token"] = page_token
        for attempt in range(3):
            try:
                r = await client.get(
                    f"{_DATA_BASE}/stocks/{symbol}/bars",
                    params=params,
                    headers=headers,
                    timeout=30.0,
                )
                if r.status_code == 429:
                    await asyncio.sleep(60)
                    continue
                r.raise_for_status()
                break
            except (httpx.NetworkError, httpx.TimeoutException):
                if attempt == 2:
                    raise
                await asyncio.sleep(2 ** attempt)
        data = r.json()
        for b in data.get("bars", []):
            bars.append({
                "date": b["t"][:10],
                "open": b["o"], "high": b["h"], "low": b["l"], "close": b["c"],
                "volume": b["v"], "vwap": b.get("vw"),
            })
        page_token = data.get("next_page_token")
        if not page_token:
            break
    return bars


def _write_bars(db_path: str, security_id: str, bars: list[dict]) -> int:
    if not bars:
        return 0
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from mentisrex.market_data.storage.duckdb_store import DuckDBStore
    rows = [
        {
            "symbol": security_id,
            "timestamp": b["date"],
            "frequency": "1d",
            "open": float(b["open"]),
            "high": float(b["high"]),
            "low": float(b["low"]),
            "close": float(b["close"]),
            "volume": int(b["volume"]),
            "vwap": float(b["vwap"]) if b.get("vwap") else None,
            "trade_count": None,
            "quality_score": None,
            "source": "alpaca_iex",
        }
        for b in bars
    ]
    store = DuckDBStore(db_path)
    try:
        return store.write_bars(rows)
    finally:
        store.close()


async def _run(
    tickers: list[str],
    ticker_to_cik: dict[str, str],
    alpaca_headers: dict,
    db_path: str,
    start: str,
    end: str,
) -> None:
    async with httpx.AsyncClient() as client:
        for ticker in tickers:
            security_id = ticker_to_cik.get(ticker.upper(), ticker.upper())
            last = _last_stored_date(db_path, security_id)
            fetch_start = (last + timedelta(days=1)).isoformat() if last else start
            if fetch_start > end:
                print(f"  {ticker}: up to date")
                continue
            try:
                bars = await _fetch_bars(client, ticker, fetch_start, end, alpaca_headers)
                n = _write_bars(db_path, security_id, bars)
                print(f"  {ticker} → {security_id}: {n} bars ({fetch_start}..{end})")
            except Exception as exc:  # noqa: BLE001
                print(f"  {ticker}: ERROR {exc}", file=sys.stderr)
            await asyncio.sleep(0.05)  # stay well under Alpaca rate limits


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tickers", nargs="*", default=[])
    p.add_argument("--ticker-file", help="file with one ticker per line")
    p.add_argument("--cik-tickers-json", help="EDGAR company_tickers.json path (pre-downloaded)")
    p.add_argument("--key", default=os.environ.get("ALPACA_PAPER_API_KEY", ""))
    p.add_argument("--secret", default=os.environ.get("ALPACA_PAPER_API_SECRET", ""))
    p.add_argument("--start", default=_DEFAULT_START)
    p.add_argument("--end", default=date.today().isoformat())
    p.add_argument("--db", default="./data/analytics.duckdb")
    p.add_argument("--edgar-user-agent", default=None,
                   help='SEC User-Agent for CIK mapping, e.g. "Name email@example.com"')
    args = p.parse_args()

    if not args.key or not args.secret:
        p.error("Alpaca credentials required: --key/--secret or ALPACA_PAPER_API_KEY/ALPACA_PAPER_API_SECRET env vars")

    tickers = list(args.tickers)
    if args.ticker_file:
        tickers += [t.strip() for t in Path(args.ticker_file).read_text().splitlines() if t.strip()]
    if not tickers:
        p.error("no tickers given")

    ticker_to_cik = _edgar_ticker_to_cik(args.edgar_user_agent)
    headers = _alpaca_headers(args.key, args.secret)

    print(f"Fetching {len(tickers)} tickers from Alpaca (IEX feed)...")
    asyncio.run(_run(tickers, ticker_to_cik, headers, args.db, args.start, args.end))
    print("Done. NOTE: IEX feed = ~2.5% of consolidated volume — daily bars only.")


if __name__ == "__main__":
    main()
