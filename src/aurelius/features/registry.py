"""Feature registry — the metadata backbone of the research platform.

A *feature* is a pure function from a trailing `Window` of bars to a single
`Decimal | None`. Its metadata (formula, inputs, version, owner, quant
documentation, validation status) lives in a frozen `FeatureSpec`. The
`@feature(...)` decorator binds the two and records them in `REGISTRY`.

Why a registry: a fund does not recompute indicators inline in strategies.
Features are defined once, versioned, documented, and reused across every
model and backtest. `REGISTRY` is the single source of truth.

Look-ahead safety is a property of how the pipeline calls features, not of the
features themselves: a feature only ever receives bars up to and including the
current one (see `pipeline.py`). Keep feature functions pure — no I/O, no
mutation, no `datetime.now()`.
"""

from __future__ import annotations

import enum
import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import NamedTuple


class Category(enum.StrEnum):
    PRICE = "price"
    VOLATILITY = "volatility"
    STATISTICAL = "statistical"
    VOLUME = "volume"
    TECHNICAL = "technical"


class ValidationStatus(enum.StrEnum):
    EXPERIMENTAL = "experimental"  # newly added, not yet vetted
    VALIDATED = "validated"        # passed the documented validation methodology
    DEPRECATED = "deprecated"      # superseded by a newer version


class Bar(NamedTuple):
    """Minimal OHLCV bar the pipeline understands. Prices are Decimal (exact)."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True)
class Window:
    """Trailing slice of bars ending at the current bar (oldest → newest).

    A feature computes its value for the *last* element. Everything in the
    window is at or before the current timestamp — there is no way to reach
    forward in time. Optional `market` holds benchmark closes aligned to the
    same timestamps, for cross-asset features (beta, correlation).
    """

    open: list[Decimal]
    high: list[Decimal]
    low: list[Decimal]
    close: list[Decimal]
    volume: list[Decimal]
    market: list[Decimal] | None = None

    def __len__(self) -> int:
        return len(self.close)


@dataclass(frozen=True)
class FeatureSpec:
    """Everything known about a feature except its code.

    The quant-documentation fields are mandatory: a feature no one can explain
    is a feature no one should trade.
    """

    name: str
    category: Category
    description: str
    formula: str
    inputs: tuple[str, ...]           # which Window series it reads
    min_periods: int                  # bars required before the value is valid
    owner: str
    version: int = 1
    frequency: str = "1d"             # calculation cadence
    status: ValidationStatus = ValidationStatus.EXPERIMENTAL
    # ── quant requirements ──
    economic_intuition: str = ""
    expected_behavior: str = ""
    failure_modes: str = ""
    validation_method: str = ""

    @property
    def key(self) -> str:
        return f"{self.name}@v{self.version}"


@dataclass(frozen=True)
class Feature:
    spec: FeatureSpec
    fn: Callable[[Window], Decimal | None]

    def __call__(self, window: Window) -> Decimal | None:
        return self.fn(window)


REGISTRY: dict[str, Feature] = {}


def feature(**spec_kwargs: object) -> Callable[
    [Callable[[Window], Decimal | None]], Feature
]:
    """Decorator: build a FeatureSpec from kwargs, bind the fn, register it.

    Registers under `name@vN`, so two versions of the same feature coexist.
    Raises on duplicate registration — never silently shadow a feature.
    """

    def wrap(fn: Callable[[Window], Decimal | None]) -> Feature:
        spec = FeatureSpec(**spec_kwargs)  # type: ignore[arg-type]
        if spec.key in REGISTRY:
            raise ValueError(f"feature already registered: {spec.key}")
        feat = Feature(spec=spec, fn=fn)
        REGISTRY[spec.key] = feat
        return feat

    return wrap


def get(name: str, version: int | None = None) -> Feature:
    """Look up a feature by name, defaulting to the highest version."""
    if version is not None:
        return REGISTRY[f"{name}@v{version}"]
    matches = [f for f in REGISTRY.values() if f.spec.name == name]
    if not matches:
        raise KeyError(name)
    return max(matches, key=lambda f: f.spec.version)


def all_features() -> list[Feature]:
    return list(REGISTRY.values())


def by_category(category: Category) -> list[Feature]:
    return [f for f in REGISTRY.values() if f.spec.category == category]


def to_definition_row(f: Feature) -> dict[str, object]:
    """Serialize a spec to the shape the feature store / Postgres persists.

    Mirrors `research.FeatureDefinition`: the registry is the code-side truth,
    this row is the durable record. `computation_config` carries formula and
    inputs so a value can be reproduced from the definition alone.
    """
    s = f.spec
    return {
        "name": s.name,
        "version": s.version,
        "category": s.category.value,
        "description": s.description,
        "computation_config": {
            "formula": s.formula,
            "inputs": list(s.inputs),
            "min_periods": s.min_periods,
            "frequency": s.frequency,
        },
        "owner": s.owner,
        "status": s.status.value,
        "economic_intuition": s.economic_intuition,
        "expected_behavior": s.expected_behavior,
        "failure_modes": s.failure_modes,
        "validation_method": s.validation_method,
    }


# ── shared math helpers (no numpy) ────────────────────────────────────────────
# Prices are Decimal; signals are approximate, so float math here is fine.
# Kept in one place so features stay one-liners.


def pct_change(series: Sequence[Decimal], lag: int = 1) -> Decimal | None:
    if len(series) <= lag or series[-1 - lag] == 0:
        return None
    return (series[-1] - series[-1 - lag]) / series[-1 - lag]


def simple_returns(series: Sequence[Decimal]) -> list[float]:
    """Consecutive simple returns as floats. Empty if <2 points."""
    out: list[float] = []
    for a, b in itertools.pairwise(series):
        if a != 0:
            out.append(float((b - a) / a))
    return out


def ema(series: Sequence[Decimal], span: int) -> float | None:
    """Exponential moving average (float). None if fewer than `span` points."""
    if len(series) < span:
        return None
    k = 2.0 / (span + 1)
    e = float(series[0])
    for x in series[1:]:
        e = float(x) * k + e * (1 - k)
    return e
