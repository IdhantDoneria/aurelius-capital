"""Invariant validation (AIDP M17).

Cheap, deterministic checks over an InstrumentBook — the guardrails the tests and the
book itself assert. Returns a list of human-readable problems (empty == healthy). No
mutation, no I/O.
"""

from __future__ import annotations

from mentisrex.research.instruments.models import CashConvention, InstrumentType


def validate_instrument(inst) -> list:
    problems = []
    if inst.contract_size <= 0:
        problems.append(f"{inst.instrument_id}: contract_size must be > 0")
    if inst.type is InstrumentType.OPTION:
        if not inst.strike or inst.strike <= 0:
            problems.append(f"{inst.instrument_id}: option needs a positive strike")
        if inst.expiry is None:
            problems.append(f"{inst.instrument_id}: option needs an expiry")
        if inst.underlying is None:
            problems.append(f"{inst.instrument_id}: option needs an underlying")
    if inst.type is InstrumentType.FUTURE and inst.cash_convention is not CashConvention.MARGINED:
        problems.append(f"{inst.instrument_id}: future must be margined")
    if inst.initial_margin_rate < inst.maintenance_margin_rate:
        problems.append(f"{inst.instrument_id}: initial margin rate below maintenance")
    return problems


def validate_book(book) -> list:
    problems = []
    for inst in book.registry.all():
        problems.extend(validate_instrument(inst))
    # every open derivative position must reference a registered instrument
    for p in book.open_positions():
        if not book.registry.has(p.instrument_id):
            problems.append(f"{p.instrument_id}: position without registered instrument")
    # margin can't be posted for an unregistered / flat contract
    for iid, m in book.margin_posted.items():
        if m < 0:
            problems.append(f"{iid}: negative margin posted")
    return problems


def is_valid(book) -> bool:
    return not validate_book(book)
