"""Trade lifecycle engine (AIDP M15).

The orchestrator. Drives each executed fill through the post-trade pipeline:

    fill received → trade booked (M11 accounting) → position updated → cash posted
    → settlement pending (T+N) → settlement completed → ledger reconciled → perf updated

Every step emits an immutable, sequenced event to the `EventLog`, so the whole run is
replayable and point-in-time safe. Reuses M11 accounting (via `PostTradeAccounting`),
consumes M14 `Fill` / `ExecutionReport` objects, and duplicates nothing — orders,
fills, positions and P&L all come from upstream milestones.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.post_trade.accounting import PostTradeAccounting
from mentisrex.research.post_trade.events import EventLog
from mentisrex.research.post_trade.ledger import CashLedger, PositionLedger, TradeLedger
from mentisrex.research.post_trade.models import (
    CashEvent,
    CashType,
    LifecycleState,
    PositionEvent,
    SettlementEvent,
    SettlementStatus,
    TradeEvent,
)
from mentisrex.research.post_trade.settlement import SettlementConfig, SettlementEngine


class PostTradeEngine:
    def __init__(self, initial_capital: float, *, settlement_config: SettlementConfig | None = None,
                 session_id: str = "post_trade") -> None:
        self.session_id = session_id
        self.initial_capital = float(initial_capital)
        self.accounting = PostTradeAccounting(initial_capital)
        self.log = EventLog()
        self.trade_ledger = TradeLedger()
        self.position_ledger = PositionLedger()
        self.cash_ledger = CashLedger(initial_capital)
        self.settlement = SettlementEngine(settlement_config)

        self.trades: dict = {}                         # trade_id -> LifecycleState
        self._cash_idx: dict = {}                       # instruction_id -> cash_ledger index
        self._seq = 0

    # ── booking ──────────────────────────────────────────────────────────────
    def book_fill(self, *, security_id: str, quantity: float, price: float, cost: float = 0.0,
                  trade_date: date | None = None, fill_id: str | None = None,
                  trade_id: str | None = None) -> str:
        if abs(quantity) < 1e-12:
            raise ValueError("cannot book a zero-quantity trade")
        tid = trade_id or self._next_trade_id()
        if tid in self.trades:
            raise ValueError(f"duplicate trade id {tid!r}")

        realized = self.accounting.book(security_id, quantity, price, cost, when=trade_date)
        self._emit_trade(tid, security_id, quantity, price, cost, LifecycleState.BOOKED,
                         trade_date, fill_id, realized, "booked")

        new_shares = self.accounting.shares(security_id)
        pos_ev = PositionEvent(
            seq=self._log_seq(), security_id=security_id, delta_shares=quantity,
            new_shares=new_shares, cost_basis=self._cost_basis(security_id),
            trade_id=tid, when=trade_date, reason="trade")
        self.position_ledger.record(pos_ev)
        self.log.append(pos_ev)

        net_cash = -(quantity * price) - cost
        inst = self.settlement.instruct(
            instruction_id=f"S-{tid}", trade_id=tid, security_id=security_id,
            quantity=quantity, cash_amount=net_cash, trade_date=trade_date)
        ce = CashEvent(seq=self._log_seq(), amount=net_cash, cash_type=CashType.TRADE,
                       trade_date=trade_date, settle_date=inst.settle_date,
                       status=SettlementStatus.PENDING, security_id=security_id, trade_id=tid)
        self._cash_idx[inst.instruction_id] = self.cash_ledger.post(ce)
        self.log.append(ce)

        self.trade_ledger.record(TradeEvent(
            seq=self._log_seq(), trade_id=tid, security_id=security_id, quantity=quantity,
            price=price, cost=cost, state=LifecycleState.SETTLEMENT_PENDING,
            trade_date=trade_date, source_fill_id=fill_id, realized_pnl=realized))
        self.trades[tid] = LifecycleState.SETTLEMENT_PENDING
        return tid

    def book_fills(self, fills, *, trade_date: date | None = None) -> list:
        """Book a list of M14 `Fill` objects (or any object with security_id/quantity/
        price/cost/fill_id)."""
        return [self.book_fill(security_id=f.security_id, quantity=f.quantity, price=f.price,
                               cost=getattr(f, "cost", 0.0),
                               trade_date=trade_date or getattr(f, "when", None),
                               fill_id=getattr(f, "fill_id", None)) for f in fills]

    def book_execution_report(self, report, *, trade_date: date | None = None) -> str | None:
        """Book a filled M14 `ExecutionReport` as one net trade at its average price."""
        if abs(report.filled_quantity) < 1e-12:
            return None
        return self.book_fill(security_id=report.security_id, quantity=report.filled_quantity,
                              price=report.avg_fill_price, cost=report.total_cost,
                              trade_date=trade_date, fill_id=report.order_id)

    # ── settlement ──────────────────────────────────────────────────────────────
    def settle(self, as_of: date) -> list:
        """Complete every instruction due on/before `as_of`. Returns settled trade ids."""
        done = []
        for inst in self.settlement.due(as_of):
            rec = self.settlement.complete(inst.instruction_id, as_of=as_of)
            self.cash_ledger.settle(self._cash_idx[inst.instruction_id])
            self.log.emit(lambda seq, i=inst, r=rec: SettlementEvent(
                seq=seq, instruction_id=i.instruction_id, trade_id=i.trade_id,
                status=SettlementStatus.COMPLETED, settle_date=i.settle_date,
                amount=r.cash_amount, detail="settled"))
            self.trades[inst.trade_id] = LifecycleState.SETTLED
            done.append(inst.trade_id)
        return done

    def fail_settlement(self, trade_id: str, *, reason: str = "settlement_failed") -> None:
        iid = f"S-{trade_id}"
        rec = self.settlement.fail(iid, reason=reason)
        self.cash_ledger.fail(self._cash_idx[iid])
        self.log.emit(lambda seq: SettlementEvent(
            seq=seq, instruction_id=iid, trade_id=trade_id, status=SettlementStatus.FAILED,
            settle_date=rec.settle_date, amount=rec.cash_amount, detail=reason))
        self.trades[trade_id] = LifecycleState.FAILED

    # ── cash injection (dividends, interest, fees not tied to a trade) ───────────
    def post_cash(self, amount: float, cash_type: CashType, *, when: date | None = None,
                  security_id: str | None = None, settled: bool = True) -> int:
        """Route a non-trade cash flow through BOTH M11's economic ledger and the
        settlement-aware post-trade ledger, so the two always reconcile."""
        self.accounting.state.ledger.post(amount, kind=cash_type.value, when=when,
                                          security_id=security_id)
        status = SettlementStatus.COMPLETED if settled else SettlementStatus.PENDING
        ce = CashEvent(seq=self._log_seq(), amount=amount, cash_type=cash_type, trade_date=when,
                       settle_date=when, status=status, security_id=security_id)
        return self.cash_ledger.post(ce)

    # ── internals ────────────────────────────────────────────────────────────────
    def _emit_trade(self, tid, sid, qty, price, cost, state, when, fill_id, realized, detail):
        self.log.emit(lambda seq: TradeEvent(
            seq=seq, trade_id=tid, security_id=sid, quantity=qty, price=price, cost=cost,
            state=state, trade_date=when, source_fill_id=fill_id, realized_pnl=realized,
            detail=detail))
        self.trades[tid] = state

    def _cost_basis(self, security_id: str) -> float:
        h = self.accounting.state.holdings.get(security_id)
        return h.cost_basis if h else 0.0

    def _log_seq(self) -> int:
        return self.log.next_seq()

    def _next_trade_id(self) -> str:
        self._seq += 1
        return f"T{self._seq:08d}"
