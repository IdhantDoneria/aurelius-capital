"""Purged & embargoed cross-validation for panel research (M31).

Plain K-fold / walk-forward leaks when labels are built from an H-day-forward
window: a training row at time i uses information through i+label_horizon, which
overlaps a test row within that horizon. Purging drops training rows whose label
window overlaps any test row; the embargo additionally drops training rows for a
few observations *after* each test block to kill serial-correlation spillover.

Follows López de Prado, *Advances in Financial Machine Learning*, ch. 7.
Index-based and deterministic — the caller maps indices to its own panel.
"""

from __future__ import annotations

from collections.abc import Iterator


def _contiguous_folds(n: int, n_splits: int) -> list[tuple[int, int]]:
    """Split range(n) into n_splits contiguous [start, end) blocks (ordered time)."""
    if n_splits < 2:
        raise ValueError("n_splits must be >= 2")
    if n_splits > n:
        raise ValueError("n_splits cannot exceed n")
    base, rem = divmod(n, n_splits)
    folds, start = [], 0
    for i in range(n_splits):
        size = base + (1 if i < rem else 0)
        folds.append((start, start + size))
        start += size
    return folds


def purged_kfold(
    n: int,
    *,
    n_splits: int = 5,
    label_horizon: int = 0,
    embargo: int = 0,
) -> Iterator[tuple[list[int], list[int]]]:
    """Yield (train_idx, test_idx) with horizon purge + embargo.

    A training index i is dropped when its label window [i, i+label_horizon]
    overlaps the test block, or when i falls in the embargo band of `embargo`
    observations after the test block. Assumes rows are time-ordered.
    """
    if label_horizon < 0 or embargo < 0:
        raise ValueError("label_horizon and embargo must be >= 0")
    folds = _contiguous_folds(n, n_splits)
    for t0, t1 in folds:
        test_idx = list(range(t0, t1))
        # Purge: training label window [i, i+H] must not reach into the test block,
        # and training rows must not sit inside the test block.
        lo = t0 - label_horizon
        hi = t1 + embargo
        train_idx = [i for i in range(n) if i < lo or i >= hi]
        yield train_idx, test_idx


def walk_forward_purged(
    n: int,
    *,
    n_splits: int = 5,
    label_horizon: int = 0,
    embargo: int = 0,
) -> Iterator[tuple[list[int], list[int]]]:
    """Expanding-window walk-forward: train only on the past, with a purge gap of
    `label_horizon + embargo` before each test block so no forward label leaks in.
    """
    if label_horizon < 0 or embargo < 0:
        raise ValueError("label_horizon and embargo must be >= 0")
    folds = _contiguous_folds(n, n_splits)
    gap = label_horizon + embargo
    for t0, t1 in folds[1:]:  # first block has no past to train on
        train_end = t0 - gap
        if train_end <= 0:
            continue
        yield list(range(train_end)), list(range(t0, t1))
