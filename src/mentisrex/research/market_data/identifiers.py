"""Security / instrument identifier mapping (AIDP M19).

Ticker != security identity. A ticker is reused across time (a delisted name's ticker is
reassigned) and differs across vendors, so all mapping is **PIT-aware**: a resolution is only
valid within its effective window. The map refuses to silently collapse two distinct
instruments onto one security — an ambiguous resolution raises rather than guessing.

Interfaces for ISIN / CUSIP / FIGI / Bloomberg / vendor ids are first-class `IdType`s; the map
is agnostic to which are populated.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class IdType(StrEnum):
    INTERNAL = "internal"  # canonical stable id (the resolution target)
    TICKER = "ticker"
    EXCHANGE_TICKER = "exchange_ticker"
    ISIN = "isin"
    CUSIP = "cusip"
    FIGI = "figi"
    BLOOMBERG = "bloomberg"
    VENDOR = "vendor"


@dataclass(frozen=True)
class IdentifierRecord:
    id_type: IdType
    value: str
    security_id: str  # internal canonical id this external id points to
    start: date | None = None  # effective from (inclusive); None == open-ended past
    end: date | None = None  # effective to (exclusive); None == open-ended future

    def covers(self, as_of: date | None) -> bool:
        if as_of is None:
            return True
        if self.start is not None and as_of < self.start:
            return False
        if self.end is not None and as_of >= self.end:
            return False
        return True


class IdentifierMap:
    """PIT-aware external-id -> internal security_id resolver."""

    def __init__(self) -> None:
        self._records: list[IdentifierRecord] = []

    def add(
        self,
        id_type: IdType,
        value: str,
        security_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> IdentifierRecord:
        rec = IdentifierRecord(IdType(id_type), str(value), str(security_id), start, end)
        # guard: same (type, value, window-overlap) must not point at two internals
        for r in self._records:
            if (
                r.id_type is rec.id_type
                and r.value == rec.value
                and r.security_id != rec.security_id
            ):
                if _windows_overlap(r, rec):
                    raise ValueError(
                        f"identifier collision: {id_type.value}:{value} maps to both "
                        f"{r.security_id} and {security_id} in overlapping windows"
                    )
        self._records.append(rec)
        return rec

    def resolve(self, id_type: IdType, value: str, *, as_of: date | None = None) -> str:
        matches = {
            r.security_id
            for r in self._records
            if r.id_type is IdType(id_type) and r.value == str(value) and r.covers(as_of)
        }
        if not matches:
            raise KeyError(f"no security for {IdType(id_type).value}:{value} as_of {as_of}")
        if len(matches) > 1:
            raise ValueError(
                f"ambiguous: {IdType(id_type).value}:{value} resolves to {sorted(matches)} "
                f"as_of {as_of} — refusing to collapse two instruments"
            )
        return next(iter(matches))

    def identifiers(self, security_id: str, *, as_of: date | None = None) -> dict:
        """All external ids known for a security at a point in time: id_type -> value."""
        out: dict = {}
        for r in self._records:
            if r.security_id == security_id and r.covers(as_of):
                out[r.id_type.value] = r.value
        return out

    def try_resolve(self, id_type: IdType, value: str, *, as_of: date | None = None) -> str | None:
        try:
            return self.resolve(id_type, value, as_of=as_of)
        except (KeyError, ValueError):
            return None


def _windows_overlap(a: IdentifierRecord, b: IdentifierRecord) -> bool:
    a0, a1 = a.start or date.min, a.end or date.max
    b0, b1 = b.start or date.min, b.end or date.max
    return a0 < b1 and b0 < a1
