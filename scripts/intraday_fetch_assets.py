"""Pull the full Alpaca US-equity asset list (active + inactive) to Parquet.

Including `inactive` assets is what makes the downstream universe
survivorship-aware: delisted tickers still have historical bars on the SIP
feed, so a point-in-time universe built from this list contains names that
later died.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path("/Users/idhantdoneria/mentisrex-capital")
OUT = ROOT / "data" / "intraday"
MAJOR = {"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS"}


def creds() -> dict[str, str]:
    for line in (ROOT / ".env.development").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)
    return {
        "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_API_SECRET"],
    }


def main() -> int:
    h = creds()
    frames = []
    for status in ("active", "inactive"):
        r = requests.get(
            "https://paper-api.alpaca.markets/v2/assets",
            params={"status": status, "asset_class": "us_equity"},
            headers=h,
            timeout=180,
        )
        r.raise_for_status()
        df = pd.DataFrame(r.json())
        df["status_at_pull"] = status
        frames.append(df)
        print(f"{status}: {len(df)}")

    assets = pd.concat(frames, ignore_index=True)
    keep = assets[
        assets["exchange"].isin(MAJOR)
        & ~assets["symbol"].str.contains(r"[^A-Z.]", regex=True, na=True)
        & (assets["symbol"].str.len() <= 5)
    ].copy()
    # Drop obvious non-common-stock share classes / rights / warrants / units.
    bad_suffix = ("W", "R", "U")
    keep = keep[~keep["symbol"].str.match(r"^[A-Z]{1,4}(W|R|U)$", na=False) | keep["symbol"].str.len().le(3)]
    keep = keep.drop_duplicates(subset=["symbol"], keep="first")
    OUT.mkdir(parents=True, exist_ok=True)
    keep.to_parquet(OUT / "assets.parquet", index=False)
    print(f"kept {len(keep)} major-exchange symbols -> {OUT / 'assets.parquet'}")
    print(keep["status_at_pull"].value_counts().to_dict())
    return 0


if __name__ == "__main__":
    sys.exit(main())
