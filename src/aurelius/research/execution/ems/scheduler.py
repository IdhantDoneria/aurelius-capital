"""Execution scheduler (AIDP M14).

Pure slicing math shared by the algorithms: turn a parent quantity into an
`ExecutionSchedule` of child slices under a chosen shape (uniform, volume-profile,
or participation-of-volume). Deterministic; the last slice absorbs rounding so
Σ child qty == parent qty exactly (no drift, no lost/created shares).
"""

from __future__ import annotations

from aurelius.research.execution.ems.models import ExecutionSchedule, ScheduleSlice


def _slices_from_fractions(order_id, algo, quantity, fractions) -> ExecutionSchedule:
    fractions = [f for f in fractions if f > 0]
    total = sum(fractions) or 1.0
    slices, allocated = [], 0.0
    for i, f in enumerate(fractions):
        if i == len(fractions) - 1:
            qty = quantity - allocated          # last slice absorbs rounding
        else:
            qty = quantity * (f / total)
            allocated += qty
        slices.append(ScheduleSlice(index=i, fraction=f / total, quantity=qty))
    return ExecutionSchedule(order_id=order_id, algo=algo, slices=slices)


def uniform_schedule(order_id, quantity, n_slices, *, algo="twap") -> ExecutionSchedule:
    n = max(1, int(n_slices))
    return _slices_from_fractions(order_id, algo, quantity, [1.0 / n] * n)


def profile_schedule(order_id, quantity, profile, *, algo="vwap") -> ExecutionSchedule:
    """Slice proportional to a volume profile (e.g. VWAP U-shape)."""
    if not profile:
        return uniform_schedule(order_id, quantity, 1, algo=algo)
    return _slices_from_fractions(order_id, algo, quantity, list(profile))


def pov_schedule(order_id, quantity, interval_volume, participation_rate, *,
                 max_slices=100, algo="pov") -> ExecutionSchedule:
    """Participate at `participation_rate` of each interval's volume until the parent
    quantity is exhausted. `interval_volume` is expected shares available per slice."""
    remaining = abs(quantity)
    per_slice = max(interval_volume * participation_rate, 0.0)
    fractions, guard = [], 0
    if per_slice <= 0 or remaining <= 0:
        return uniform_schedule(order_id, quantity, 1, algo=algo)
    while remaining > 1e-9 and guard < max_slices:
        take = min(per_slice, remaining)
        fractions.append(take / abs(quantity))
        remaining -= take
        guard += 1
    return _slices_from_fractions(order_id, algo, quantity, fractions)
