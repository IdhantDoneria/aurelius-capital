"""AIDP M19 — Institutional Market Data, Curve Calibration & Volatility Surface Engine.

The layer *underneath* M18 valuation: it turns raw market sources into the immutable,
PIT-validated `MarketDataSnapshot` that M18 consumes. Sources → normalization → quality → PIT →
canonical observations → curve/vol calibration → snapshot. Reuses M18 curves/surfaces/snapshot,
M16 FX, M15 serialization; never duplicates the valuation, FX or risk engines.
"""

from __future__ import annotations

__version__ = "1.0.0"
