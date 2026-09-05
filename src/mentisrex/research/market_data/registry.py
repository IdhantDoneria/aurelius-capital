"""Market-data component registry (AIDP M19).

Governance for the pluggable pieces: providers, curve builders, curve conventions, volatility
calibrators, surface models, calendars and fixing providers. Every registered component is
identified by (kind, name, version) so a snapshot/curve/surface can name exactly which component
produced it — the same governance discipline M18's `ModelRegistry` applies to pricing models.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ComponentKind(StrEnum):
    PROVIDER = "provider"
    CURVE_BUILDER = "curve_builder"
    CONVENTION = "convention"
    VOL_CALIBRATOR = "vol_calibrator"
    SURFACE_MODEL = "surface_model"
    CALENDAR = "calendar"
    FIXING_PROVIDER = "fixing_provider"


@dataclass(frozen=True)
class ComponentInfo:
    kind: ComponentKind
    name: str
    version: str
    description: str = ""


class MarketDataRegistry:
    def __init__(self) -> None:
        self._components: dict = {}

    def register(self, info: ComponentInfo) -> ComponentInfo:
        key = (info.kind, info.name, info.version)
        if key in self._components and self._components[key] != info:
            raise ValueError(
                f"{info.kind.value}:{info.name}@{info.version} already registered differently"
            )
        self._components[key] = info
        return info

    def get(self, kind: ComponentKind, name: str, version: str) -> ComponentInfo:
        try:
            return self._components[(ComponentKind(kind), name, version)]
        except KeyError:
            raise KeyError(f"unknown component {kind}:{name}@{version}") from None

    def by_kind(self, kind: ComponentKind) -> list:
        return [v for k, v in sorted(self._components.items()) if k[0] is ComponentKind(kind)]

    def all(self) -> list:
        return [self._components[k] for k in sorted(self._components)]


def default_market_data_registry() -> MarketDataRegistry:
    """The components M19 ships, declared for governance."""
    r = MarketDataRegistry()
    for info in (
        ComponentInfo(ComponentKind.PROVIDER, "static", "1.0.0", "Fixed raw records"),
        ComponentInfo(ComponentKind.PROVIDER, "historical", "1.0.0", "Date-keyed PIT records"),
        ComponentInfo(ComponentKind.PROVIDER, "mock", "1.0.0", "Deterministic synthetic"),
        ComponentInfo(
            ComponentKind.CURVE_BUILDER,
            "bootstrap.sequential",
            "1.0.0",
            "Deposits/OIS/FRA/futures/swaps bisection bootstrap",
        ),
        ComponentInfo(
            ComponentKind.CURVE_BUILDER, "credit.hazard", "1.0.0", "Par-CDS hazard bootstrap"
        ),
        ComponentInfo(ComponentKind.CONVENTION, "ACT_360.simple", "1.0.0", "Money-market"),
        ComponentInfo(ComponentKind.CONVENTION, "ACT_365.continuous", "1.0.0", "Curve default"),
        ComponentInfo(ComponentKind.VOL_CALIBRATOR, "sabr.hagan", "1.0.0", "Hagan lognormal SABR"),
        ComponentInfo(ComponentKind.VOL_CALIBRATOR, "svi.raw", "1.0.0", "Gatheral raw SVI"),
        ComponentInfo(ComponentKind.SURFACE_MODEL, "interpolated", "1.0.0", "Bilinear grid"),
        ComponentInfo(ComponentKind.CALENDAR, "US", "1.0.0", "US business days"),
        ComponentInfo(ComponentKind.CALENDAR, "UK", "1.0.0", "UK business days"),
        ComponentInfo(ComponentKind.CALENDAR, "IN", "1.0.0", "India business days"),
        ComponentInfo(
            ComponentKind.FIXING_PROVIDER, "store.bitemporal", "1.0.0", "PIT versioned fixings"
        ),
    ):
        r.register(info)
    return r
