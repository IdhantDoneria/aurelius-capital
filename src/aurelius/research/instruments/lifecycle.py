"""InstrumentBook — the multi-asset orchestrator (AIDP M17).

Holds ONE reused M15 `PostTradeEngine` as the cash/equity book of record and layers a
derivative overlay on top: an `InstrumentRegistry`, a `DerivativePosition` per non-equity
contract, margin/collateral accounts, and an append-only `InstrumentEvent` log (reusing the
M15 `EventLog`). Backward compatibility is structural — an equity trade delegates straight
to `PostTradeEngine.book_fill`, so an equity-only book *is* M15, byte for byte.

Cash discipline: there is exactly one cash ledger (M11's, via the engine). Every derivative
cash flow — premium, initial margin, variation margin, settlement — is posted through
`engine.post_cash`, so M11/M15/M16 accounting stays the single source of truth.
"""

from __future__ import annotations

from datetime import date

from aurelius.research.instruments import instrument as _econ
from aurelius.research.instruments import margin as _margin
from aurelius.research.instruments.models import (
    CashConvention,
    Instrument,
    InstrumentEvent,
    InstrumentEventType,
    InstrumentType,
)
from aurelius.research.instruments.positions import DerivativePosition
from aurelius.research.instruments.registry import InstrumentRegistry
from aurelius.research.post_trade.events import EventLog
from aurelius.research.post_trade.lifecycle import PostTradeEngine
from aurelius.research.post_trade.models import CashType


class InstrumentBook:
    def __init__(self, initial_capital: float = 0.0, *, engine: PostTradeEngine | None = None,
                 registry: InstrumentRegistry | None = None, session_id: str = "instr_book") -> None:
        self.session_id = session_id
        self.engine = engine or PostTradeEngine(initial_capital, session_id=session_id)
        self.registry = registry or InstrumentRegistry()
        self.positions: dict = {}             # instrument_id -> DerivativePosition (derivatives only)
        self.margin_posted: dict = {}         # instrument_id -> posted margin (cash)
        self.collateral: dict = {}            # instrument_id -> CollateralBalance
        self.events = EventLog()
        self._closed: set = set()             # instruments settled/expired/terminated

    # ── registration ────────────────────────────────────────────────────────────
    def register(self, inst: Instrument) -> Instrument:
        self.registry.register(inst)
        self._emit(InstrumentEventType.CREATION, inst.instrument_id, detail=inst.type.value)
        return inst

    def _emit(self, t, iid, **kw) -> InstrumentEvent:
        return self.events.emit(lambda seq: InstrumentEvent(seq=seq, type=t, instrument_id=iid, **kw))

    def _inst(self, ref) -> Instrument:
        if isinstance(ref, Instrument):
            if not self.registry.has(ref.instrument_id):
                self.register(ref)
            return self.registry.get(ref.instrument_id)
        return self.registry.get(ref)

    def _pos(self, inst: Instrument) -> DerivativePosition:
        p = self.positions.get(inst.instrument_id)
        if p is None:
            p = self.positions[inst.instrument_id] = DerivativePosition(inst)
        return p

    @property
    def cash(self) -> float:
        return self.engine.accounting.cash

    # ── trading ──────────────────────────────────────────────────────────────────
    def book_trade(self, instrument, quantity: float, price: float, *, cost: float = 0.0,
                   trade_date: date | None = None) -> str:
        """Book a fill for any asset class. Equities take the identical M15 path;
        derivatives update the overlay and post only real cash through the M11 ledger."""
        inst = self._inst(instrument)
        if abs(quantity) < 1e-12:
            raise ValueError("cannot book a zero-quantity trade")
        if inst.instrument_id in self._closed:
            raise ValueError(f"{inst.instrument_id} is closed (expired/settled)")

        if inst.type is InstrumentType.EQUITY:                     # identical to pre-M17
            tid = self.engine.book_fill(security_id=inst.instrument_id, quantity=quantity,
                                        price=price, cost=cost, trade_date=trade_date)
            self._emit(InstrumentEventType.TRADE, inst.instrument_id, quantity=quantity,
                       price=price, cash=-(quantity * price) - cost, when=trade_date, data={"tid": tid})
            return tid

        pos = self._pos(inst)
        pos.apply(quantity, price)
        cash = _econ.trade_cash(inst, quantity, price, cost)
        ct = CashType.PREMIUM if inst.type is InstrumentType.OPTION else CashType.MARGIN
        if inst.cash_convention is CashConvention.PRINCIPAL:      # bond principal
            ct = CashType.PREMIUM if inst.type is InstrumentType.OPTION else CashType.TRADE
        if abs(cash) > 1e-12:
            self.engine.post_cash(cash, ct, when=trade_date, security_id=inst.instrument_id)
        self._post_initial_margin(inst, pos, price, trade_date)
        self._emit(InstrumentEventType.TRADE, inst.instrument_id, quantity=quantity,
                   price=price, cash=cash, when=trade_date)
        return f"{inst.instrument_id}:{len(self.events)}"

    def _post_initial_margin(self, inst, pos, mark, when) -> None:
        if inst.initial_margin_rate <= 0:
            return
        req = _margin.requirement(inst, pos.quantity, mark).initial
        delta = req - self.margin_posted.get(inst.instrument_id, 0.0)
        if abs(delta) > 1e-12:                                    # post/release margin as cash
            self.engine.post_cash(-delta, CashType.MARGIN, when=when, security_id=inst.instrument_id)
            pos.margin = req
        if req <= 1e-12:                                          # flat → drop the margin line
            self.margin_posted.pop(inst.instrument_id, None)
        else:
            self.margin_posted[inst.instrument_id] = req

    # ── mark-to-market ────────────────────────────────────────────────────────────
    def mark(self, marks: dict, *, when: date | None = None) -> dict:
        """Mark every position. Equities re-mark M11 state; margined derivatives post
        variation margin cash; option/bond marks only move unrealized value. Returns the
        variation-margin cash posted per instrument."""
        equity_marks = {sid: m for sid, m in marks.items()
                        if self.registry.has(sid)
                        and self.registry.get(sid).type is InstrumentType.EQUITY}
        if equity_marks:
            self.engine.accounting.mark(equity_marks)
        vm_posted = {}
        for iid, pos in self.positions.items():
            if iid not in marks:
                continue
            vm = pos.mark(marks[iid])
            inst = self.registry.get(iid)
            if inst.cash_convention is CashConvention.MARGINED:
                # true daily settlement: variation margin realizes the day's P&L in cash and
                # re-bases the contract to the settlement mark, so unrealized stays 0 (the P&L
                # is not counted twice — once in cash, once as unrealized).
                if abs(vm) > 1e-12:
                    self.engine.post_cash(vm, CashType.MARGIN, when=when, security_id=iid)
                    vm_posted[iid] = vm
                pos.realized_pnl += vm
                pos.avg_price = marks[iid]
            self._post_initial_margin(inst, pos, marks[iid], when)
            self._emit(InstrumentEventType.MARK_TO_MARKET, iid, price=marks[iid], cash=vm, when=when)
        return vm_posted

    def close(self, instrument, price: float, *, when: date | None = None) -> None:
        """Flatten a derivative position at `price` (used by expiry/exercise/settlement)."""
        inst = self._inst(instrument)
        pos = self.positions.get(inst.instrument_id)
        if pos is None or pos.quantity == 0:
            return
        self.book_trade(inst, -pos.quantity, price, trade_date=when)
        if self.margin_posted.get(inst.instrument_id):           # release remaining margin
            rel = self.margin_posted.pop(inst.instrument_id)
            self.engine.post_cash(rel, CashType.MARGIN, when=when, security_id=inst.instrument_id)
            pos.margin = 0.0

    # ── reporting ─────────────────────────────────────────────────────────────────
    def snapshot(self, instrument_id: str):
        p = self.positions.get(instrument_id)
        return p.snapshot() if p else None

    def open_positions(self) -> list:
        return [p.snapshot() for iid, p in sorted(self.positions.items()) if p.quantity != 0]

    def realized_pnl(self) -> float:
        eq = self.engine.accounting.realized_pnl()
        deriv = sum(p.realized_pnl for p in self.positions.values())
        return eq + deriv

    def unrealized_pnl(self) -> float:
        eq = self.engine.accounting.unrealized_pnl()
        deriv = sum(p.snapshot().unrealized_pnl for p in self.positions.values())
        return eq + deriv
