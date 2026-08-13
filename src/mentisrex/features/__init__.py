"""Institutional feature-engineering platform.

Import side effect: loading `mentisrex.features` registers every built-in
feature, so `registry.REGISTRY` / `all_features()` are populated on import.

Typical use:
    from mentisrex.features import FeaturePipeline, FeatureStore, all_features, Bar

    pipe = FeaturePipeline()
    rows = pipe.compute_symbol("AAPL", bars)   # bars: list[Bar]
    store = FeatureStore(":memory:")
    store.sync_definitions(all_features())
    store.write_values(rows)
"""

from mentisrex.features import library as _library  # noqa: F401  (registers features)
from mentisrex.features.pipeline import FeaturePipeline, FeatureValueRow
from mentisrex.features.registry import (
    REGISTRY,
    Bar,
    Category,
    Feature,
    FeatureSpec,
    ValidationStatus,
    Window,
    all_features,
    by_category,
    get,
)
from mentisrex.features.store import FeatureStore

__all__ = [
    "REGISTRY",
    "Bar",
    "Category",
    "Feature",
    "FeaturePipeline",
    "FeatureSpec",
    "FeatureStore",
    "FeatureValueRow",
    "ValidationStatus",
    "Window",
    "all_features",
    "by_category",
    "get",
]
