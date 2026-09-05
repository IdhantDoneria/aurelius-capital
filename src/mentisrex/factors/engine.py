"""FactorEngine base class for cross-sectional signal computation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date


class FactorEngine(ABC):
    """Base class for factor signal engines.

    All signals are percentile-ranked (0-1) cross-sectionally before return.
    Missing / NaN securities are dropped — callers never see None values.
    """

    @abstractmethod
    def compute(
        self, as_of: date, *, knowledge_date: date | None = None
    ) -> dict[str, dict[str, float]]:
        """Return {factor_name: {security_id: signal_value}} for all factors."""
        ...

    @abstractmethod
    def compute_factor(
        self, name: str, as_of: date, *, knowledge_date: date | None = None
    ) -> dict[str, float]:
        """Single factor cross-section. Returns {security_id: signal_value}."""
        ...


if __name__ == "__main__":
    from mentisrex.factors.nse import NSEFactorEngine
    from mentisrex.factors.us import USFactorEngine

    assert issubclass(USFactorEngine, FactorEngine)
    assert issubclass(NSEFactorEngine, FactorEngine)
    assert hasattr(USFactorEngine, "compute")
    assert hasattr(USFactorEngine, "compute_factor")
    assert hasattr(NSEFactorEngine, "compute")
    assert hasattr(NSEFactorEngine, "compute_factor")
    print("ok")
