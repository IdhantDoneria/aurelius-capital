"""Classify each symbol as a fund (ETF/ETN/commodity trust) or an operating
company, and write the mapping to Parquet.

All three strategies rest on claims about *single-name* behaviour: clientele
segmentation across a company's overnight and intraday sessions, a company
being repriced after news, mechanical index flow into a company's closing
auction. None of those claims is about an index product, and an ETF that
tracks the very index the book is neutralised against is not a position, it
is a hedge wearing a stock's clothing.

Left in, they also distort selection in a specific and damaging way: a
liquidity screen ranked by dollar volume and filtered on tight spreads
promotes large ETFs ahead of every operating company, so an intraday
"stock in play" screen returns SPY, GLD and a 1-3 month T-bill fund.

Detection is positive -- match the fund, not the company. The alternative,
keeping only names whose description ends in "Common Stock", fails because
the broker applies that suffix inconsistently: Apple has it, Boeing and Bank
of America do not.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

DATA = Path("/Users/idhantdoneria/mentisrex-capital/data/intraday")

FUND_ISSUER = (
    r"iShares|SPDR|State Street|Vanguard|Invesco|ProShares|Direxion|\bARK\b|Schwab|"
    r"WisdomTree|VanEck|Global X|First Trust|Xtrackers|Franklin FTSE|Amplify|"
    r"Simplify|JPMorgan Beta|Pacer|Roundhill|YieldMax|Defiance|GraniteShares|"
    r"Krane|Sprott|abrdn|Grayscale|Bitwise|Fidelity Covington|Dimensional"
)
FUND_WORD = r"\bETF\b|\bETN\b|\bTrust\b|\bFund\b|\bFunds\b|\bShares\b|\bPortfolio\b|\bIndex\b|\bSeries\b"
FUND_STRONG = r"\bETF\b|\bETNs?\b|Index Fund|Bond Fund|\bUCITS\b|\bFund,? (LP|L\.P\.)\b|\bCommodity Trust\b"


def is_fund(name: str | None) -> bool:
    n = name or ""
    if re.search(FUND_STRONG, n, re.I):
        return True
    return bool(re.search(FUND_ISSUER, n, re.I) and re.search(FUND_WORD, n, re.I))


def main() -> int:
    a = pd.read_parquet(DATA / "assets.parquet")[["symbol", "name", "exchange"]]
    a["is_fund"] = a["name"].map(is_fund)
    a.to_parquet(DATA / "security_class.parquet", index=False)
    print(f"{len(a):,} symbols, {int(a['is_fund'].sum()):,} classified as funds")
    print(f"-> {DATA / 'security_class.parquet'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
