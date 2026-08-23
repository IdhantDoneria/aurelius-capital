"""India momentum-quality programme (M42).

A long-only, leverage-capped (1.5x hard ceiling) Indian equity strategy:
decile momentum + real fundamentals-based quality stock selection, a
worse-of-two-signals exposure overlay, sector caps, and inverse-volatility
position sizing. See `docs/MENTISREX_M42_INDIA_TRADING_HANDBOOK.md` for the
full specification, backtest results, and known limitations.

This package is deliberately NOT a peer of `mentisrex.programme` (the US
v3.0 ten-sleeve engine) — it has no broker integration, no state
persistence, no CLI, and no live risk-gate enforcement. It is a research/
backtest engine only. See the handbook's "Engineering maturity" section for
exactly what would need to be built before this could run live, and why
that was not attempted in this pass.
"""

from mentisrex.programme_india.config import IndiaConfig, DEFAULT_CONFIG

__all__ = ["IndiaConfig", "DEFAULT_CONFIG"]
