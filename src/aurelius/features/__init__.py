"""Institutional feature-engineering platform.

Import side effect: loading `aurelius.features` registers every built-in
feature, so `registry.REGISTRY` / `all_features()` are populated on import.

Typical use:
    from aurelius.features import FeaturePipeline, FeatureStore, all_features, Bar

    pipe = FeaturePipeline()
    rows = pipe.compute_symbol("AAPL", bars)   # bars: list[Bar]
    store = FeatureStore(":memory:")
    store.sync_definitions(all_features())
    store.write_values(rows)
"""

from aurelius.features import library as _library  # noqa: F401  (registers features)
from aurelius.features.pipeline import FeaturePipeline, FeatureValueRow
from aurelius.features.registry import (
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
from aurelius.features.store import FeatureStore

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
