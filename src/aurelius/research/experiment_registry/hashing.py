"""Deterministic metadata hashing (AIDP Phase 7).

Fingerprints are computed over *metadata* — versions, counts, feature lists,
parameters — never raw datasets. Same logical inputs → same hash, forever, on any
machine. Ordering never matters: dicts are canonicalized with sorted keys.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonical(obj: Any) -> str:
    """Order-independent JSON: dict keys sorted (recursively), compact separators.
    List order is preserved (it's meaningful); dict order is not."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _digest(text: str) -> str:
    return hashlib.blake2b(text.encode(), digest_size=16).hexdigest()


def hash_params(params: dict | None) -> str:
    """Parameter-set hash, independent of key ordering.
    {"lookback":252,"top":50} == {"top":50,"lookback":252}."""
    return _digest(_canonical(params or {}))


def hash_features(features: list[str] | None) -> str:
    """Feature-set hash, independent of list ordering (a set of features)."""
    return _digest(_canonical(sorted(features or [])))


def feature_registry_version(registry: dict) -> str:
    """Content version of the feature registry: hash of {name: (source, field,
    direction)}. Changes iff the registry's definitions change."""
    flat = {k: list(v) for k, v in registry.items()}
    return _digest(_canonical(flat))


def dataset_fingerprint(dataset_versions: dict) -> str:
    """Immutable fingerprint of the DATA an experiment saw — append-only versions,
    row counts, registry version. No raw data touched."""
    return _digest(_canonical(dataset_versions))


def experiment_fingerprint(dataset_versions: dict, features: list[str] | None,
                           params: dict | None) -> str:
    """Full run identity = data + feature set + parameters. Two runs sharing this
    are reproductions of each other (duplicate detection key)."""
    return _digest(_canonical({
        "dataset": dataset_fingerprint(dataset_versions),
        "features": hash_features(features),
        "params": hash_params(params),
    }))
