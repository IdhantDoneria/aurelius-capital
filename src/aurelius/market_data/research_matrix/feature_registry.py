"""Feature registry (AIDP Phase 6).

Each feature maps to (source, field, direction). The engine computes one bundle
per source per security (a price window, a factor-input dict, an insider signal)
and pulls named fields out of it — so adding a feature that reads an existing
source field is a one-line registry edit, no engine change.

`source` ∈ {price, fundamental, insider} routes to the right PIT accessor and,
critically, the right identity key: price→PIT ticker, fundamental→CIK,
insider→security_id. That's the single-key normalization the spec asks for — one
security_id row, three source keys resolved through SecurityMaster, no ticker
joins duplicated.

`direction` = the sign of "good" for a long/short factor ("higher"|"lower"); it's
carried through to the matrix metadata, not applied here (no factor optimization
in this layer).
"""

from __future__ import annotations

# name: (source, field-in-source-bundle, direction)
FEATURES: dict[str, tuple[str, str, str]] = {
    # ── price (PIT ticker → PitPriceStore.window_as_of) ──────────────────────
    "close":         ("price", "close", "higher"),
    "returns":       ("price", "returns", "higher"),
    "volatility":    ("price", "volatility", "lower"),
    "volume":        ("price", "volume", "higher"),
    "dollar_volume": ("price", "dollar_volume", "higher"),
    # ── fundamental (CIK → FundamentalsEngine.factor_inputs_as_of) ───────────
    "market_cap":       ("fundamental", "market_cap", "higher"),
    "book_value":       ("fundamental", "book_value", "higher"),
    "earnings_yield":   ("fundamental", "earnings_yield", "higher"),
    "cashflow_yield":   ("fundamental", "cash_flow_yield", "higher"),
    "roe":              ("fundamental", "roe", "higher"),
    "roa":              ("fundamental", "roa", "higher"),
    "operating_margin": ("fundamental", "operating_margin", "higher"),
    "leverage":         ("fundamental", "debt_to_equity", "lower"),
    # ── insider (security_id → InsiderEngine.insider_signal_as_of) ───────────
    "insider_buy_value":  ("insider", "buy_value", "higher"),
    "insider_sell_value": ("insider", "sell_value", "lower"),
    "net_insider_value":  ("insider", "net_value", "higher"),
    "insider_count":      ("insider", "insider_count", "higher"),
    "cluster_buy":        ("insider", "cluster_buy", "higher"),
}

SOURCES = ("price", "fundamental", "insider")
