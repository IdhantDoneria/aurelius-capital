"""Canonical market-data domain models (AIDP M19).

The single typed vocabulary every raw feed is normalized *into*. A `CanonicalObservation` is
one immutable, PIT-tagged, provenance-carrying market datum — never reduced to a bare float:
its `obs_type`/`field`/`unit`/`currency` keep the semantics explicit so downstream code knows
whether a number is a price, a rate, a discount factor or an implied vol.

Reuses the M18 `Provenance` stamp — M19 does not fork PIT provenance, it extends it with the
richer observation envelope (revision, unit, quality status, observation type).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import Enum

from aurelius.research.valuation.models import Provenance


# ── typed enums (semantics stay explicit) ────────────────────────────────────

class ObservationType(str, Enum):
    TRADE = "trade"
    QUOTE = "quote"
    CLOSE = "close"
    ADJ_CLOSE = "adjusted_close"
    CORPORATE_ACTION = "corporate_action"
    DIVIDEND = "dividend"
    SPLIT = "split"
    FX_RATE = "fx_rate"
    INTEREST_RATE = "interest_rate"
    YIELD = "yield"
    DISCOUNT_FACTOR = "discount_factor"
    FORWARD = "forward"
    VOLATILITY = "volatility"
    VOLUME = "volume"
    OPEN_INTEREST = "open_interest"
    REFERENCE = "reference"


class Unit(str, Enum):
    PRICE = "price"              # currency per share/unit
    RATE = "rate"               # decimal (0.05 == 5%)
    PERCENT = "percent"         # 5.0 == 5%
    BASIS_POINT = "basis_point"  # 50 == 0.005
    FACTOR = "factor"           # dimensionless (discount factor, split ratio)
    SHARES = "shares"
    CONTRACTS = "contracts"
    VOL = "vol"                 # annualized vol as a decimal
    NONE = "none"


class QualityStatus(str, Enum):
    RAW = "raw"                 # straight off a source, not yet checked
    VALIDATED = "validated"     # passed the quality engine
    SUSPECT = "suspect"         # flagged (WARNING/ERROR) but retained
    REJECTED = "rejected"       # failed a REJECT rule — never valued


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    REJECT = "reject"


# ── the canonical datum ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class CanonicalObservation:
    """One market datum with full semantics + PIT + provenance + revision.

    `observation_date` is when the value was *knowable*; `effective_date` is the date the value
    is *for*. A close printed 2024-01-03 for the 2024-01-02 session has observation_date
    2024-01-03, effective_date 2024-01-02. PIT reads gate on `observation_date`.
    """
    security_id: str                       # canonical/internal stable id
    obs_type: ObservationType
    field: str                             # "close" | "bid" | "ask" | "zero_rate" | ...
    value: float
    observation_date: date                 # when knowable
    effective_date: date                   # what date it is for
    source: str = "unknown"
    timestamp: datetime | None = None
    currency: str | None = None
    unit: Unit = Unit.PRICE
    status: QualityStatus = QualityStatus.RAW
    revision: int = 0                      # 0 == original; higher == later restatement
    meta: dict = field(default_factory=dict)   # bid/ask/volume/open/high/low & source extras

    def provenance(self) -> Provenance:
        return Provenance(source=self.source, observation_date=self.observation_date,
                          effective_date=self.effective_date, timestamp=self.timestamp,
                          currency=self.currency, instrument_id=self.security_id)

    def with_status(self, status: QualityStatus) -> "CanonicalObservation":
        return replace(self, status=status)

    @property
    def key(self) -> tuple:
        """Identity of *what* is observed (source/revision-independent)."""
        return (self.security_id, self.obs_type.value, self.field, self.effective_date)

    def fingerprint(self) -> str:
        parts = [self.security_id, self.obs_type.value, self.field, f"{self.value:.12g}",
                 str(self.observation_date), str(self.effective_date), self.source,
                 self.currency or "", self.unit.value, str(self.revision)]
        return hashlib.blake2b("|".join(parts).encode(), digest_size=8).hexdigest()


@dataclass(frozen=True)
class QualityDiagnostic:
    """A structured finding from normalization or the quality engine. No silent repair —
    the datum is classified, the reason is recorded."""
    code: str
    severity: Severity
    message: str
    security_id: str | None = None
    field: str | None = None

    @property
    def rejects(self) -> bool:
        return self.severity is Severity.REJECT
