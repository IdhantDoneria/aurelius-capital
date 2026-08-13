"""Corporate actions (AIDP M15).

Applies dated, auditable, replayable corporate actions to the reused M11 book via the
accounting adapter. Position mechanics (splits, stock dividends, mergers, renames,
liquidation) go through `PostTradeAccounting`; cash impact is routed through
`PostTradeEngine.post_cash` so M11's economic cash and the settlement-aware ledger stay
reconciled. Every action emits a `CorporateActionEvent`.

Supported: cash dividend, stock dividend, split, reverse split, merger, symbol change,
delisting. Rights issues are an interface (event emitted, no position change) — the
subscription-economics model is a documented extension.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.post_trade.models import (
    CashType,
    CorporateActionEvent,
    DelistingEvent,
    DividendEvent,
    LifecycleState,
    MergerEvent,
    PositionEvent,
    SplitEvent,
    SymbolChangeEvent,
)


def apply(engine, action, *, when: date | None = None) -> CorporateActionEvent:
    when = when or action.ex_date
    sid = action.security_id
    shares = engine.accounting.shares(sid)
    cash_impact = 0.0
    new_id = getattr(action, "new_security_id", None) or sid
    affected = {sid, new_id}
    before = {s: engine.accounting.shares(s) for s in affected}

    if isinstance(action, DividendEvent) and action.stock_ratio:
        engine.accounting.add_shares(sid, shares * action.stock_ratio)
    elif isinstance(action, DividendEvent):
        cash_impact = shares * action.amount_per_share
        if cash_impact:
            engine.post_cash(cash_impact, CashType.DIVIDEND, when=when, security_id=sid)
    elif isinstance(action, SplitEvent):
        engine.accounting.adjust_split(sid, action.ratio)
    elif isinstance(action, MergerEvent):
        if action.cash_per_share and shares:
            cash_impact = shares * action.cash_per_share
            engine.post_cash(cash_impact, CashType.CORPORATE_ACTION, when=when, security_id=sid)
        if new_id != sid:
            engine.accounting.rename(sid, new_id)
        if action.share_ratio != 1.0:
            engine.accounting.adjust_split(new_id, action.share_ratio)
    elif isinstance(action, SymbolChangeEvent):
        engine.accounting.rename(sid, new_id)
    elif isinstance(action, DelistingEvent):
        engine.accounting.close_position(sid, action.final_price, when=when)
        cash_impact = shares * action.final_price
    # else (rights issue / unknown): interface only — event still recorded

    # Emit one position event per affected security from the before/after diff, so the
    # position ledger's net always matches the M11 book even under renames/mergers.
    position_impact = 0.0
    for s in sorted(affected):
        delta = engine.accounting.shares(s) - before[s]
        if abs(delta) > 1e-12:
            position_impact += abs(delta)
            pos_ev = PositionEvent(
                seq=engine.log.next_seq(), security_id=s, delta_shares=delta,
                new_shares=engine.accounting.shares(s), cost_basis=engine._cost_basis(s),
                trade_id=None, when=when, reason="corporate_action")
            engine.position_ledger.record(pos_ev)
            engine.log.append(pos_ev)

    ev = engine.log.emit(lambda seq: CorporateActionEvent(
        seq=seq, action_id=action.action_id, action_type=action.action_type, security_id=sid,
        ex_date=when, cash_impact=cash_impact, position_impact=position_impact,
        detail=action.detail or action.action_type))
    engine.trades.setdefault(action.action_id, LifecycleState.RECONCILED)
    return ev
