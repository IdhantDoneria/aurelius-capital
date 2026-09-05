"""Sealed, immutable forward-cycle record (M25).

One ForwardCycleRecord per evaluation cycle, per strategy, per account.

Design guarantees:
  - Cycle identity is deterministic from (strategy_id, strategy_version, evaluation_date).
  - Sealing is irreversible: sealed_at is written once and never overwritten.
  - Provider revisions cannot mutate a sealed record — the sealed snapshot_fingerprint
    captures exactly what was used during that evaluation.
  - Failed cycles produce a FAILED record, never silently become SUCCESS.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime


class CycleStatus:
    SUCCESS = "SUCCESS"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    ALREADY_SEALED = "ALREADY_SEALED"


def make_forward_cycle_id(strategy_id: str, strategy_version: str, evaluation_date: date) -> str:
    """Deterministic, human-readable cycle identity key.

    Same inputs always produce the same cycle_id. Running the same month twice
    detects the existing sealed record and refuses to re-execute.

    Format: {strategy_id}__{evaluation_date.year}_{evaluation_date.month:02d}
    e.g.:   ew-momentum-exp__2026_08
    """
    return f"{strategy_id}__{evaluation_date.year}_{evaluation_date.month:02d}"


@dataclass
class ForwardCycleRecord:
    """Complete audit record for one PAPER_FORWARD evaluation cycle.

    All fields are populated before sealing. Once sealed_at is set the record
    must not be modified — the store enforces this by skipping writes when the
    cycle file already exists.

    Sections mirror M25 spec §7:
      IDENTITY / DATA / RESEARCH / EXECUTION / ACCOUNTING / RISK /
      OPERATIONS / PROVENANCE
    """

    # ── IDENTITY ──────────────────────────────────────────────────────────────
    cycle_id: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    strategy_fingerprint: str = ""
    evaluation_date: date | None = None  # logical month (year/month only)
    knowledge_as_of: date | None = None  # actual snapshot as_of date
    account_id: str = "paper-default"

    # ── DATA ──────────────────────────────────────────────────────────────────
    provider: str = "yahoo_finance"
    snapshot_fingerprint: str = ""  # fingerprint of snapshot used
    observations_accepted: int = 0
    observations_rejected: int = 0
    pit_violations: int = 0
    stale_observations: int = 0
    missing_securities: list = field(default_factory=list)

    # ── RESEARCH ──────────────────────────────────────────────────────────────
    universe: list = field(default_factory=list)
    signal_outputs: dict = field(default_factory=dict)  # security_id → signal_value
    portfolio_weights: dict = field(default_factory=dict)
    evaluation_fingerprint: str = ""
    evaluation_id: str = ""

    # ── EXECUTION ─────────────────────────────────────────────────────────────
    orders_generated: int = 0
    fills: int = 0
    slippage_bps: float = 0.0

    # ── ACCOUNTING ────────────────────────────────────────────────────────────
    starting_nav: float = 0.0
    ending_nav: float = 0.0
    cash: float = 0.0
    positions: dict = field(default_factory=dict)  # security_id → shares
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    gross_return: float = 0.0
    net_return: float = 0.0
    turnover: float = 0.0

    # ── RISK ──────────────────────────────────────────────────────────────────
    risk_approved: bool = False
    risk_decision: str = ""
    concentration: float = 0.0  # max single-position weight

    # ── OPERATIONS ────────────────────────────────────────────────────────────
    start_time: str = ""
    end_time: str = ""
    fetch_latency_s: float = 0.0
    processing_latency_s: float = 0.0
    status: str = CycleStatus.PARTIAL
    skip_reason: str = ""
    error_message: str = ""

    # ── PROVENANCE ────────────────────────────────────────────────────────────
    campaign_id: str = ""
    mode: str = "PAPER_FORWARD"
    sealed_at: str = ""  # ISO datetime string; non-empty ↔ immutable

    # ── ALPACA EXECUTION (M29) ────────────────────────────────────────────────
    broker: str = "SIMULATED"  # "ALPACA" when Alpaca paper was used
    alpaca_account_id_masked: str = ""  # first 8 chars + "..." only
    reconciliation_status: str = ""  # "PASS" | "FAIL" | "NOT_VERIFIED" | ""
    positions_reconciled: bool = False
    nav_reconciled: bool = False
    nav_delta_bps: float = 0.0  # Alpaca equity vs internal NAV in bps

    # ── public API ────────────────────────────────────────────────────────────

    def seal(self, status: str = CycleStatus.SUCCESS) -> None:
        """Mark this record as permanently immutable. Idempotent."""
        if not self.sealed_at:
            self.status = status
            self.sealed_at = datetime.now(UTC).replace(tzinfo=None).isoformat()

    @property
    def is_sealed(self) -> bool:
        return bool(self.sealed_at)

    def record_fingerprint(self) -> str:
        """Stable fingerprint of the cycle's financial outcome."""
        body = json.dumps(
            {
                "cycle_id": self.cycle_id,
                "snapshot_fingerprint": self.snapshot_fingerprint,
                "ending_nav": self.ending_nav,
                "fills": self.fills,
                "status": self.status,
            },
            sort_keys=True,
        )
        return hashlib.blake2b(body.encode(), digest_size=16).hexdigest()

    def to_dict(self) -> dict:
        d: dict = {}
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            if isinstance(v, date) and not isinstance(v, datetime):
                d[f.name] = v.isoformat()
            else:
                d[f.name] = v
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ForwardCycleRecord:
        kw = {k: v for k, v in d.items() if k in {f.name for f in dataclasses.fields(cls)}}
        for date_key in ("evaluation_date", "knowledge_as_of"):
            raw = kw.get(date_key)
            if isinstance(raw, str) and raw:
                kw[date_key] = date.fromisoformat(raw)
        return cls(**kw)
