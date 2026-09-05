"""FX conversion (AIDP M16).

Turns a provider rate into an explicit, auditable `FXConversion` — source/target
currency, amounts, effective rate, direction (direct/inverse/cross/identity), as-of and
provider. No implicit conversion happens anywhere else in M16; everything routes through
here so every currency change leaves a record.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.fx.currency import validate_code
from mentisrex.research.fx.models import ConversionDirection, FXConversion


def convert(
    provider,
    amount: float,
    from_ccy: str,
    to_ccy: str,
    *,
    as_of: date | None = None,
    reason: str = "fx",
    conversion_id: str | None = None,
) -> FXConversion:
    """Convert `amount` of `from_ccy` into `to_ccy` at the provider's as-of rate."""
    from_ccy, to_ccy = validate_code(from_ccy), validate_code(to_ccy)
    rate, direction, source = provider.resolve(from_ccy, to_ccy, as_of=as_of)
    return FXConversion(
        conversion_id=conversion_id or f"FX-{from_ccy}{to_ccy}-{as_of}",
        from_currency=from_ccy,
        to_currency=to_ccy,
        from_amount=float(amount),
        to_amount=float(amount) * rate,
        rate=rate,
        direction=direction,
        as_of=as_of,
        source=source,
        reason=reason,
    )


def convert_to_target(
    provider,
    target_amount: float,
    from_ccy: str,
    to_ccy: str,
    *,
    as_of: date | None = None,
    reason: str = "fx",
    conversion_id: str | None = None,
) -> FXConversion:
    """How much `from_ccy` is needed to obtain exactly `target_amount` of `to_ccy`."""
    rate, _, _ = provider.resolve(validate_code(from_ccy), validate_code(to_ccy), as_of=as_of)
    return convert(
        provider,
        float(target_amount) / rate,
        from_ccy,
        to_ccy,
        as_of=as_of,
        reason=reason,
        conversion_id=conversion_id,
    )


def round_trip_error(
    provider, amount: float, a: str, b: str, *, as_of: date | None = None
) -> float:
    """|convert(a→b→a) − amount|; should be ~0 within numerical tolerance."""
    fwd = convert(provider, amount, a, b, as_of=as_of)
    back = convert(provider, fwd.to_amount, b, a, as_of=as_of)
    return abs(back.to_amount - amount)


def conversion_to_dict(c: FXConversion) -> dict:
    return {
        "conversion_id": c.conversion_id,
        "from_currency": c.from_currency,
        "to_currency": c.to_currency,
        "from_amount": c.from_amount,
        "to_amount": c.to_amount,
        "rate": c.rate,
        "direction": c.direction.value,
        "as_of": c.as_of.isoformat() if c.as_of else None,
        "source": c.source,
        "reason": c.reason,
    }


def conversion_from_dict(d: dict) -> FXConversion:
    return FXConversion(
        conversion_id=d["conversion_id"],
        from_currency=d["from_currency"],
        to_currency=d["to_currency"],
        from_amount=d["from_amount"],
        to_amount=d["to_amount"],
        rate=d["rate"],
        direction=ConversionDirection(d["direction"]),
        as_of=date.fromisoformat(d["as_of"]) if d["as_of"] else None,
        source=d["source"],
        reason=d.get("reason", "fx"),
    )
