"""Settlement engine (AIDP M15).

T+N settlement with a business-day calendar (weekends + optional holidays skipped via
`numpy.busday_offset`). Tracks pending / completed / failed settlement instructions and
the cash they move. Deterministic: settlement dates are a pure function of the trade
date and the configured horizon; completion is driven by an injected `as_of` date, not
a wall clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from mentisrex.research.post_trade.models import (
    SettlementInstruction,
    SettlementRecord,
    SettlementReport,
    SettlementStatus,
)


@dataclass
class SettlementConfig:
    default_days: int = 2  # T+2
    per_security: dict = field(default_factory=dict)  # security_id -> T+N override
    holidays: tuple = ()  # ISO date strings, skipped

    def horizon(self, security_id: str) -> int:
        return self.per_security.get(security_id, self.default_days)


def settlement_date(trade_date: date, days: int, holidays: tuple = ()) -> date:
    """T+`days` business days after `trade_date` (weekends/holidays skipped)."""
    if trade_date is None:
        return None
    if days <= 0:
        return trade_date
    hol = np.array(holidays, dtype="datetime64[D]")  # empty array when none
    out = np.busday_offset(np.datetime64(trade_date, "D"), days, roll="forward", holidays=hol)
    return out.astype("O")


class SettlementEngine:
    def __init__(self, config: SettlementConfig | None = None) -> None:
        self.config = config or SettlementConfig()
        self.instructions: dict = {}  # instruction_id -> SettlementInstruction
        self.records: dict = {}  # instruction_id -> SettlementRecord

    def instruct(
        self,
        *,
        instruction_id: str,
        trade_id: str,
        security_id: str,
        quantity: float,
        cash_amount: float,
        trade_date: date,
    ) -> SettlementInstruction:
        sd = settlement_date(trade_date, self.config.horizon(security_id), self.config.holidays)
        inst = SettlementInstruction(
            instruction_id=instruction_id,
            trade_id=trade_id,
            security_id=security_id,
            quantity=quantity,
            cash_amount=cash_amount,
            trade_date=trade_date,
            settle_date=sd,
            status=SettlementStatus.PENDING,
        )
        self.instructions[instruction_id] = inst
        return inst

    def due(self, as_of: date) -> list:
        return [
            i
            for i in self.instructions.values()
            if i.status == SettlementStatus.PENDING
            and i.settle_date is not None
            and i.settle_date <= as_of
        ]

    def complete(self, instruction_id: str, *, as_of: date) -> SettlementRecord:
        inst = self.instructions[instruction_id]
        rec = SettlementRecord(
            instruction_id=instruction_id,
            trade_id=inst.trade_id,
            settle_date=inst.settle_date,
            completed_on=as_of,
            cash_amount=inst.cash_amount,
            status=SettlementStatus.COMPLETED,
        )
        self.records[instruction_id] = rec
        self.instructions[instruction_id] = _restatus(inst, SettlementStatus.COMPLETED)
        return rec

    def fail(self, instruction_id: str, *, reason: str = "settlement_failed") -> SettlementRecord:
        inst = self.instructions[instruction_id]
        rec = SettlementRecord(
            instruction_id=instruction_id,
            trade_id=inst.trade_id,
            settle_date=inst.settle_date,
            completed_on=None,
            cash_amount=inst.cash_amount,
            status=SettlementStatus.FAILED,
            detail=reason,
        )
        self.records[instruction_id] = rec
        self.instructions[instruction_id] = _restatus(inst, SettlementStatus.FAILED)
        return rec

    # ── views ─────────────────────────────────────────────────────────────────
    def settled_cash_flow(self) -> float:
        return sum(
            r.cash_amount for r in self.records.values() if r.status == SettlementStatus.COMPLETED
        )

    def pending(self) -> list:
        return [i for i in self.instructions.values() if i.status == SettlementStatus.PENDING]

    def report(self, as_of: date | None = None) -> SettlementReport:
        pend = self.pending()
        failed = [i for i in self.instructions.values() if i.status == SettlementStatus.FAILED]
        completed = [r for r in self.records.values() if r.status == SettlementStatus.COMPLETED]
        return SettlementReport(
            as_of=as_of,
            n_pending=len(pend),
            n_completed=len(completed),
            n_failed=len(failed),
            pending_cash=sum(i.cash_amount for i in pend),
            settled_cash=self.settled_cash_flow(),
            settlement_exposure=sum(abs(i.cash_amount) for i in pend),
            failed_instruction_ids=sorted(i.instruction_id for i in failed),
        )


def _restatus(inst: SettlementInstruction, status: SettlementStatus) -> SettlementInstruction:
    from dataclasses import replace

    return replace(inst, status=status)
