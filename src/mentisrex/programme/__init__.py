"""Mentis Rex Capital — US Equity Systematic Programme v3.0.

The ten-sleeve levered core-satellite programme. This package is the strategy
core: four directional sleeves on the benchmark plus six market-neutral
cross-sectional sleeves, combined into one book under a hard gross cap, charged
for transaction costs *and* for the cost of carrying leverage.

Design principle, taken from the specification and enforced here: the live path
and the research path execute the same functions. There is deliberately no
second implementation of any signal, because two implementations that were once
identical are the most common source of live-versus-backtest divergence.

Numeric core is float64 pandas/numpy. Values are converted to Decimal only at
the broker boundary in `execution.py`.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "3.0.0"
