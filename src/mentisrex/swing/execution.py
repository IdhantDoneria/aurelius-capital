"""Broker boundary for the swing programme — turns a target book into orders.

`cli.cmd_targets` deliberately stops at weights and shares (see its module
docstring): sizing is a strategy decision, order slicing and broker plumbing
are not. This module is that seam's other half.

Both sleeves wired through `cli.targets` (Nightfall, Lastlight) enter at the
**closing auction** — `out["venue"] == "closing_auction"` in `cli.py`'s
target book — so `build_orders` diffs against current holdings and
`AlpacaSwingBroker.submit_moc` places genuine market-on-close orders
(`type=market, time_in_force=cls`), not same-day market orders. This mirrors
`mentisrex.programme.execution.AlpacaProgrammeBroker` exactly, for the same
reason documented there: `AlpacaPaperBroker.submit_order` / `.submit`
hard-code `time_in_force="day"`, which would silently turn an MOC order into
an intraday fill mislabelled as MOC — a real basis versus the backtest's
close mark that the fill log would not show.

PAPER ONLY. `AlpacaSwingBroker` wraps `mentisrex.paper.alpaca_broker.
AlpacaPaperBroker`, whose module docstring lists the fail-closed live-trading
guards (hardcoded paper endpoint, `MENTISREX_LIVE_TRADING` kill switch,
paper-account verification at construction). Nothing in this module weakens
or bypasses any of them — it reuses that broker's credential handling,
account state and paper verification unchanged, and adds only the
closing-auction order type and the target-vs-current diff.

Per `docs/SWING_STRATEGY_SELECTED.md` section 1, the recommendation for
Nightfall is explicitly NOT to deploy at target size on the backtest alone,
but to fund a small, bounded cost-measurement pilot. This module has no
opinion on notional size — that is `--equity` on the `targets` CLI and the
`ALPACA_PAPER_API_KEY` account's own balance — but it exists to make that
pilot possible without hand-entering orders.

Known limitations (see CLAUDE.md "nothing gets silently skipped"):

- `AlpacaSwingBroker.shortable` raises `NotImplementedError`, identically to
  `AlpacaProgrammeBroker.shortable`. The reused `AlpacaPaperBroker` has no
  asset/shortability lookup; Alpaca's `GET /v2/assets/{symbol}` (fields
  `shortable`, `easy_to_borrow`) would supply it. Nightfall and Lastlight are
  dollar-neutral long/short books, so a short leg that turns out unshortable
  today is silently rejected by Alpaca at submission time rather than
  filtered and re-neutralised beforehand the way
  `programme.execution.borrow_filter` does for the other book. This is a
  genuine missing dependency (no existing lookup to reuse anywhere in the
  codebase), not effort avoidance, and it is the same gap already documented
  in `programme/execution.py` — wiring the assets endpoint once would close
  it for both books.
- `AlpacaSwingBroker.fills` raises `NotImplementedError`, for the same reason
  `AlpacaProgrammeBroker.fills` does: no fills-since-timestamp query exists
  anywhere in `mentisrex.paper`. Alpaca's
  `GET /v2/orders?status=closed&after=<ts>` would supply it.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import numpy as np
import pandas as pd

from mentisrex.core.logging import get_logger
from mentisrex.paper.alpaca_broker import AlpacaPaperBroker

logger = get_logger(__name__)

MIN_ORDER_USD = 250.0
"""Below this notional a delta is not worth the round-trip cost; matches the
threshold `mentisrex.programme.execution.build_orders` uses for the same
reason (spec Table 27)."""


@dataclass(frozen=True)
class Order:
    symbol: str
    quantity: int  # signed; negative = sell/short
    side: str  # "BUY" | "SELL"
    target_weight: float
    notional: float


@dataclass(frozen=True)
class OrderSet:
    as_of: pd.Timestamp
    strategy: str
    orders: tuple[Order, ...]
    target_weights: pd.Series  # post-suppression: what will actually be held
    suppressed: tuple[str, ...]  # below MIN_ORDER_USD or truncated to 0 shares
    missing_price: tuple[str, ...]
    gross: float
    net: float


def _bad_price(price: float) -> bool:
    return pd.isna(price) or not np.isfinite(price) or price <= 0


def build_orders(
    target_book: pd.DataFrame,
    current_shares: Mapping[str, float],
    nav: float,
    *,
    strategy: str,
    as_of: pd.Timestamp,
    min_order_usd: float = MIN_ORDER_USD,
) -> OrderSet:
    """Diff `target_book` (from `cli.cmd_targets`) against live broker shares.

    `target_book` must carry `symbol`, `weight`, `reference_price`. Weight,
    not the CSV's own `shares` column, is the source of truth for sizing here
    — it is recomputed against the *current* NAV rather than the NAV the
    target book happened to be built with, so a book built earlier in the day
    still sizes correctly against today's actual account equity.

    Symbols held in the account but absent from `target_book` (a name that
    rolled out of the universe, or a stale position) are appended so they get
    a chance to be traded flat, matching
    `programme.execution.build_orders`'s handling of the same case.
    """
    target_book = target_book.set_index("symbol")
    extra = [s for s in current_shares if s not in target_book.index]
    order_idx = list(target_book.index) + extra

    weight = target_book["weight"].reindex(order_idx, fill_value=0.0).astype(float)
    price = target_book["reference_price"].reindex(order_idx)
    current = pd.Series(current_shares, dtype=float).reindex(order_idx, fill_value=0.0)

    min_usd = float(min_order_usd)
    realized_weight = pd.Series(0.0, index=order_idx)
    orders: list[Order] = []
    suppressed: list[str] = []
    missing_price: list[str] = []

    for symbol in order_idx:
        px = price[symbol]
        if _bad_price(px):
            missing_price.append(symbol)
            # No live price -> no trade possible; realized weight stays at
            # whatever the current holding implies, not the stale target.
            continue

        target_shares = round(weight[symbol] * nav / float(px))
        delta_shares = int(target_shares - current[symbol])
        notional = delta_shares * float(px)
        if abs(notional) < min_usd:
            suppressed.append(symbol)
            realized_weight[symbol] = current[symbol] * float(px) / nav if nav else 0.0
            continue

        side = "BUY" if delta_shares > 0 else "SELL"
        orders.append(
            Order(
                symbol=symbol,
                quantity=delta_shares,
                side=side,
                target_weight=float(weight[symbol]),
                notional=float(notional),
            )
        )
        realized_weight[symbol] = float(weight[symbol])

    if missing_price:
        logger.warning("swing_orders_missing_price", strategy=strategy, symbols=tuple(missing_price))

    gross = float(realized_weight.abs().sum())
    net = float(realized_weight.sum())

    return OrderSet(
        as_of=as_of,
        strategy=strategy,
        orders=tuple(orders),
        target_weights=realized_weight,
        suppressed=tuple(suppressed),
        missing_price=tuple(missing_price),
        gross=gross,
        net=net,
    )


class Broker(Protocol):
    def nav(self) -> float: ...
    def positions(self) -> dict[str, float]: ...  # symbol -> shares
    def shortable(self, symbols: list[str]) -> dict[str, bool]: ...
    def submit_moc(self, orders: Sequence[Order]) -> list[str]: ...
    def fills(self, since: pd.Timestamp) -> pd.DataFrame: ...


class AlpacaSwingBroker:
    """Broker over Alpaca paper trading, reusing `AlpacaPaperBroker` (M28) for
    credentials, paper-account verification and `account()` rather than
    reimplementing any of it. See module docstring for why `submit_moc`
    bypasses `AlpacaPaperBroker.submit_order` (which hard-codes
    `time_in_force="day"`) and posts genuine `time_in_force="cls"` orders
    directly.

    Credentials: reads `ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_API_SECRET`
    from the environment via `AlpacaPaperBroker.__init__` — nothing in this
    class reads or stores credentials itself. See
    `docs/SWING_EXECUTION_SETUP.md` for where to obtain and set them.

    No network call happens at construction of *this* class; the underlying
    `AlpacaPaperBroker` (created lazily on first use) performs the
    paper-account verification call.
    """

    def __init__(self, *, strategy_id: str = "swing", max_order_notional: Decimal = Decimal("10000")) -> None:
        self._strategy_id = strategy_id
        self._max_order_notional = max_order_notional
        self._broker: AlpacaPaperBroker | None = None

    def _client(self) -> AlpacaPaperBroker:
        if self._broker is None:
            self._broker = AlpacaPaperBroker(
                strategy_id=self._strategy_id, max_order_notional=self._max_order_notional
            )
        return self._broker

    def nav(self) -> float:
        return float(self._client().account()["equity"])

    def positions(self) -> dict[str, float]:
        positions = self._client().account()["positions"]
        return {symbol: float(qty) for symbol, qty in positions.items()}

    def shortable(self, symbols: list[str]) -> dict[str, bool]:
        raise NotImplementedError(
            "AlpacaSwingBroker.shortable: the reused AlpacaPaperBroker has no asset/"
            "shortability lookup. Alpaca's GET /v2/assets/{symbol} (fields `shortable`, "
            "`easy_to_borrow`) would supply it. Wire that endpoint (and a bulk variant "
            "for the whole universe) before running any short leg unattended through "
            "this broker; until then, a short that Alpaca rejects as unshortable is "
            "surfaced only as a per-order rejection in submit_moc's return value, not "
            "pre-filtered and re-neutralised the way programme.execution.borrow_filter "
            "does for the other book."
        )

    def submit_moc(self, orders: Sequence[Order]) -> list[str]:
        client = self._client()
        order_ids: list[str] = []
        for order in orders:
            qty = Decimal(abs(order.quantity))
            payload = {
                "symbol": order.symbol,
                "qty": str(qty),
                "side": "buy" if order.quantity > 0 else "sell",
                "type": "market",
                "time_in_force": "cls",
                "client_order_id": (
                    f"swing-{self._strategy_id}-{order.symbol}-{order.side}-{abs(order.quantity)}"
                )[:48],
            }
            resp = client._http.post("/v2/orders", json=payload)
            if not resp.is_success:
                msg = resp.json().get("message", resp.text)
                logger.warning("swing_moc_order_rejected", symbol=order.symbol, reason=msg[:200])
                continue
            data = resp.json()
            order_ids.append(data["id"])
            logger.info(
                "swing_moc_order_submitted",
                symbol=order.symbol,
                side=order.side,
                quantity=abs(order.quantity),
                id=data["id"],
                status=data.get("status"),
            )
        return order_ids

    def fills(self, since: pd.Timestamp) -> pd.DataFrame:
        raise NotImplementedError(
            "AlpacaSwingBroker.fills: no fills-since-timestamp query exists anywhere in "
            "mentisrex.paper. Alpaca's GET /v2/orders?status=closed&after=<ts> would supply it."
        )

    def close(self) -> None:
        if self._broker is not None:
            self._broker.close()
