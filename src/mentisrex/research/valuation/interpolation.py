"""Deterministic 1-D interpolation (AIDP M18).

Linear and log-linear interpolation with an explicit extrapolation policy. Curves interpolate
zero rates linearly (or discount factors log-linearly); vol surfaces interpolate linearly in
both dimensions. Kept minimal on purpose — splines are a documented future extension.
"""

from __future__ import annotations

import bisect
from enum import StrEnum


class Extrapolation(StrEnum):
    FLAT = "flat"  # hold the nearest endpoint value
    LINEAR = "linear"  # extend the terminal slope
    ERROR = "error"  # raise outside the knot range


def _locate(xs: list, x: float) -> int:
    return bisect.bisect_left(xs, x)


def linear(xs: list, ys: list, x: float, *, extrap: Extrapolation = Extrapolation.FLAT) -> float:
    """Piecewise-linear interpolation over sorted `xs`. Deterministic, O(log n) lookup."""
    if len(xs) != len(ys) or not xs:
        raise ValueError("xs/ys must be non-empty and equal length")
    if len(xs) == 1:
        return ys[0]
    if x <= xs[0]:
        if x == xs[0]:
            return ys[0]
        return _extrapolate(xs, ys, x, extrap, left=True)
    if x >= xs[-1]:
        if x == xs[-1]:
            return ys[-1]
        return _extrapolate(xs, ys, x, extrap, left=False)
    i = _locate(xs, x)
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _extrapolate(xs, ys, x, extrap, *, left: bool) -> float:
    if extrap is Extrapolation.ERROR:
        raise ValueError(f"x={x} outside knot range [{xs[0]}, {xs[-1]}]")
    if extrap is Extrapolation.FLAT:
        return ys[0] if left else ys[-1]
    # LINEAR: extend terminal slope
    if left:
        x0, x1, y0, y1 = xs[0], xs[1], ys[0], ys[1]
    else:
        x0, x1, y0, y1 = xs[-2], xs[-1], ys[-2], ys[-1]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def log_linear(
    xs: list, ys: list, x: float, *, extrap: Extrapolation = Extrapolation.FLAT
) -> float:
    """Log-linear interpolation (for discount factors — keeps forward rates piecewise-constant)."""
    import math

    if any(y <= 0 for y in ys):
        raise ValueError("log_linear requires positive ys")
    ly = [math.log(y) for y in ys]
    return math.exp(linear(xs, ly, x, extrap=extrap))


def bilinear(
    xs: list,
    ys: list,
    grid: list,
    x: float,
    y: float,
    *,
    extrap: Extrapolation = Extrapolation.FLAT,
) -> float:
    """Bilinear interpolation on a grid[i][j] indexed by xs[i], ys[j] (vol surfaces)."""
    row = [linear(ys, grid[i], y, extrap=extrap) for i in range(len(xs))]
    return linear(xs, row, x, extrap=extrap)
