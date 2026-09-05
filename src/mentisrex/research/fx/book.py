"""Multi-currency portfolio book (AIDP M16).

The orchestrator. It does **not** re-implement accounting: it holds one reused M15
`PostTradeEngine` **per currency** — each a self-contained single-currency post-trade
book (its own M11 `PortfolioState`, cash ledger, settlement, event log) denominated in
that currency. On top it adds only the FX overlay: cross-currency cash movement via
explicit `FXConversion`s, a running FX cash position (for realized FX P&L), and
base-currency valuation.

Backward compatibility falls out of the structure: a book whose only currency is the
base, with a unit rate, delegates every call to exactly one `PostTradeEngine` — i.e. it
*is* M15. Single-currency behaviour is unchanged.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.fx import conversion as _conv
from mentisrex.research.fx.currency import CurrencyMismatchError, validate_code
from mentisrex.research.fx.models import FXHedge
from mentisrex.research.post_trade.lifecycle import PostTradeEngine
from mentisrex.research.post_trade.models import CashType
from mentisrex.research.post_trade.settlement import SettlementConfig


class MultiCurrencyBook:
    def __init__(
        self,
        base_currency: str,
        provider,
        *,
        initial: dict | None = None,
        settlement_config: SettlementConfig | None = None,
        session_id: str = "fx_book",
    ) -> None:
        self.base_currency = validate_code(base_currency)
        self.provider = provider
        self.settlement_config = settlement_config
        self.session_id = session_id
        self.books: dict = {}  # ccy -> PostTradeEngine
        self.security_currency: dict = {}  # security_id -> trading ccy
        self.conversions: list = []  # FXConversion (audit)
        self.hedges: list = []  # FXHedge
        self.realized_fx_pnl = 0.0  # base-currency FX result on conversions
        self._fx_pos: dict = {}  # ccy -> [units, avg_base_rate]
        self._conv_seq = 0

        for ccy, amt in (initial or {}).items():
            self._book(ccy, initial=amt)
        self._book(self.base_currency)  # base book always exists

    # ── per-currency books ─────────────────────────────────────────────────────
    def _book(self, ccy: str, *, initial: float = 0.0) -> PostTradeEngine:
        ccy = validate_code(ccy)
        eng = self.books.get(ccy)
        if eng is None:
            eng = PostTradeEngine(
                initial,
                settlement_config=self.settlement_config,
                session_id=f"{self.session_id}:{ccy}",
            )
            self.books[ccy] = eng
        return eng

    def book(self, ccy: str) -> PostTradeEngine:
        return self._book(ccy)

    def currencies(self) -> list:
        return sorted(self.books)

    def base_rate(self, ccy: str, when: date | None = None) -> float:
        """FX rate translating one unit of `ccy` into the base currency."""
        ccy = validate_code(ccy)
        return (
            1.0
            if ccy == self.base_currency
            else self.provider.rate(ccy, self.base_currency, as_of=when)
        )

    # ── trading ────────────────────────────────────────────────────────────────
    def book_fill(
        self,
        *,
        security_id: str,
        quantity: float,
        price: float,
        cost: float = 0.0,
        currency: str,
        funding_currency: str | None = None,
        trade_date: date | None = None,
        fill_id: str | None = None,
        trade_id: str | None = None,
    ) -> str:
        """Book a fill priced in `currency` (the security's trading currency). If
        `funding_currency` differs and this is a buy, first convert exactly enough of the
        funding currency into the trading currency (an explicit cross-currency trade)."""
        currency = validate_code(currency)
        prev = self.security_currency.get(security_id)
        if prev and prev != currency:
            raise CurrencyMismatchError(f"{security_id} trades in {prev}, got {currency}")
        self.security_currency[security_id] = currency
        eng = self._book(currency)

        if funding_currency and validate_code(funding_currency) != currency and quantity > 0:
            self.convert(
                needed_to=quantity * price + cost,
                from_currency=funding_currency,
                to_currency=currency,
                when=trade_date,
                reason="trade_funding",
            )

        return eng.book_fill(
            security_id=security_id,
            quantity=quantity,
            price=price,
            cost=cost,
            trade_date=trade_date,
            fill_id=fill_id,
            trade_id=trade_id,
        )

    # ── FX conversion ──────────────────────────────────────────────────────────
    def convert(
        self,
        *,
        amount: float | None = None,
        needed_to: float | None = None,
        from_currency: str,
        to_currency: str,
        when: date | None = None,
        settled: bool = True,
        reason: str = "fx",
    ):
        """Move cash between two currency books via an explicit conversion. Provide
        either `amount` (of from_currency) or `needed_to` (target of to_currency)."""
        from_ccy, to_ccy = validate_code(from_currency), validate_code(to_currency)
        self._conv_seq += 1
        cid = f"FX{self._conv_seq:08d}"
        if needed_to is not None:
            fxc = _conv.convert_to_target(
                self.provider,
                needed_to,
                from_ccy,
                to_ccy,
                as_of=when,
                reason=reason,
                conversion_id=cid,
            )
        else:
            fxc = _conv.convert(
                self.provider,
                amount,
                from_ccy,
                to_ccy,
                as_of=when,
                reason=reason,
                conversion_id=cid,
            )

        self._book(from_ccy).post_cash(-fxc.from_amount, CashType.TRADE, when=when, settled=settled)
        self._book(to_ccy).post_cash(fxc.to_amount, CashType.TRADE, when=when, settled=settled)
        self._apply_fx_position(fxc, when)
        self.conversions.append(fxc)
        return fxc

    def _apply_fx_position(self, fxc, when) -> None:
        self._reduce_fx(fxc.from_currency, fxc.from_amount, when)  # realize on the way out
        self._add_fx(fxc.to_currency, fxc.to_amount, when)  # acquire at current rate

    def _add_fx(self, ccy: str, units: float, when) -> None:
        if ccy == self.base_currency or units <= 0:
            return
        br = self.base_rate(ccy, when)
        pos = self._fx_pos.setdefault(ccy, [0.0, br])
        tot = pos[0] + units
        pos[1] = (pos[0] * pos[1] + units * br) / tot if tot else br
        pos[0] = tot

    def _reduce_fx(self, ccy: str, units: float, when) -> None:
        if ccy == self.base_currency or units <= 0:
            return
        pos = self._fx_pos.get(ccy)
        if not pos or pos[0] <= 1e-12:
            return  # currency not acquired via FX (e.g. sale proceeds)
        take = min(units, pos[0])
        self.realized_fx_pnl += (self.base_rate(ccy, when) - pos[1]) * take
        pos[0] -= take

    # ── settlement / cash / hedging pass-throughs ──────────────────────────────
    def settle(self, as_of: date) -> dict:
        return {c: eng.settle(as_of) for c, eng in self.books.items()}

    def fail_settlement(self, currency: str, trade_id: str, **kw) -> None:
        self._book(currency).fail_settlement(trade_id, **kw)

    def post_cash(
        self,
        currency: str,
        amount: float,
        cash_type: CashType,
        *,
        when: date | None = None,
        security_id: str | None = None,
        settled: bool = True,
    ) -> int:
        return self._book(currency).post_cash(
            amount, cash_type, when=when, security_id=security_id, settled=settled
        )

    def add_hedge(self, hedge: FXHedge) -> FXHedge:
        self.hedges.append(hedge)
        return hedge

    def mark(self, prices: dict) -> None:
        """Mark holdings by security. Prices are in each security's trading currency."""
        by_ccy: dict = {}
        for sid, p in prices.items():
            c = self.security_currency.get(sid)
            if c:
                by_ccy.setdefault(c, {})[sid] = p
        for c, pr in by_ccy.items():
            self.books[c].accounting.mark(pr)
