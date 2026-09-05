"""OIS / multi-curve framework (AIDP M19).

Extends M18's single-curve world to the post-2008 reality: a **discount** curve (e.g. OIS),
one or more **projection/forecast** curves (the index a floating leg fixes off), and named
**basis** curves. Purely generic — no index (SOFR/ESTR/EURIBOR) is hard-coded; you inject the
bootstrapped `ZeroCurve`s and label them. Discounting uses the discount curve, forward rates
project off the projection curve; that separation is the whole point of multi-curve.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mentisrex.research.valuation.curves import ZeroCurve


@dataclass(frozen=True)
class MultiCurveSet:
    """One discount curve + optional projection + named basis curves, all M18 `ZeroCurve`s."""

    discount: ZeroCurve
    projection: ZeroCurve | None = None
    basis: dict = field(default_factory=dict)  # name -> ZeroCurve
    label: str = ""

    def project(self) -> ZeroCurve:
        """The curve floating legs fix off (falls back to discount in a single-curve world)."""
        return self.projection or self.discount

    def discount_factor(self, t: float) -> float:
        return self.discount.discount(t)

    def forward_rate(self, t1: float, t2: float) -> float:
        """Projected simple forward between t1 and t2 (off the projection curve)."""
        return self.project().forward_rate(t1, t2)

    def basis_curve(self, name: str) -> ZeroCurve:
        c = self.basis.get(name)
        if c is None:
            raise KeyError(f"no basis curve {name!r} in set {self.label!r}")
        return c

    def fingerprint(self) -> str:
        import hashlib

        parts = [
            self.discount.fingerprint(),
            self.projection.fingerprint() if self.projection else "-",
        ]
        parts += [f"{k}:{v.fingerprint()}" for k, v in sorted(self.basis.items())]
        return hashlib.blake2b("|".join(parts).encode(), digest_size=8).hexdigest()


def single_curve(curve: ZeroCurve) -> MultiCurveSet:
    """Wrap one curve as its own discount and projection (single-curve compatibility)."""
    return MultiCurveSet(discount=curve, projection=curve, label=curve.curve_id)


def ois_multicurve(
    discount: ZeroCurve, projection: ZeroCurve, *, basis=None, label: str = "multicurve"
) -> MultiCurveSet:
    """OIS-discounted, index-projected set. `discount` = OIS, `projection` = the index curve."""
    return MultiCurveSet(
        discount=discount, projection=projection, basis=dict(basis or {}), label=label
    )
