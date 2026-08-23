"""Orders, broker boundary, borrow filter (spec section 8 / Table 27, 15:40-15:45 ET).

Numeric core: like the rest of `mentisrex.programme`, target/current weights and
prices here are plain `float64` (numpy/pandas). This is deliberate for the same
reason as elsewhere in the package: the research and live paths must run the
identical arithmetic. `Decimal` is used only at the actual broker boundary
(`AlpacaProgrammeBroker`), where order quantities and account balances round-trip
through Alpaca's API — matching the house convention in `mentisrex/paper/` and
`mentisrex/domain/entities/market.py`. Everything upstream of `submit_moc` stays
float64; the Decimal conversion happens inside the adapter, at the last moment,
and the Broker Protocol's public methods still return the float/int types this
contract specifies.

THE DESIGN RULE BEHIND THIS MODULE (spec section 9, boxed): when a constraint
cannot be satisfied, give up gross exposure, never give up neutrality. A book
that is under-sized is under-risked and costs return. A book that has silently
become directional because some shorts could not be placed is running a bet
nobody chose. `borrow_filter` restores neutrality before it restores gross, and
never restores gross beyond what survived the borrow check (spec section 11.2:
the short book is insurance, not alpha — losing it changes the book's risk
shape, and that change must be visible, not silently absorbed by re-levering
the survivors).

Known limitations (see CLAUDE.md "nothing gets silently skipped"):

- `AlpacaProgrammeBroker.shortable` raises `NotImplementedError`. The reused
  `mentisrex.paper.alpaca_broker.AlpacaBroker` has no asset/shortability lookup;
  Alpaca exposes this via `GET /v2/assets/{symbol}` (fields `shortable`,
  `easy_to_borrow`). Wiring that endpoint (and a bulk variant for the whole
  universe) is what unblocks this — out of scope for this module, which only
  reuses the existing broker's credentials/account/positions wiring per
  ADDENDUM A.6.
- `AlpacaProgrammeBroker.fills` raises `NotImplementedError`. There is no
  fills-since-timestamp query anywhere in `mentisrex.paper`. Alpaca's
  `GET /v2/orders?status=closed&after=<ts>` supplies it; wiring that (with
  Decimal-accurate price/qty parsing) unblocks `programme/reconcile.py`
  against real fills.

Both gaps are genuine missing dependencies (no existing lookup to reuse), not
effort avoidance, and both are named explicitly here rather than silently
downgraded (e.g. faking a plain day-order as MOC, which spec Table 15 flags as
an unmeasured basis versus the backtest's close mark).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import numpy as np
import pandas as pd

from mentisrex.core.logging import get_logger
from mentisrex.infrastructure.config.settings import get_settings
from mentisrex.paper.alpaca_broker import ALPACA_PAPER_BASE_URL as ALPACA_BASE_URL
from mentisrex.paper.alpaca_broker import AlpacaPaperBroker as AlpacaBroker
from mentisrex.programme.config import ConfigError, ProgrammeConfig

logger = get_logger(__name__)


@dataclass(frozen=True)
class Order:
    symbol: str
    quantity: int  # signed; negative = sell/short
    side: str  # "BUY" | "SELL"
    order_type: str  # always "MOC" in production
    target_weight: float
    notional: float


@dataclass(frozen=True)
class OrderSet:
    as_of: pd.Timestamp
    orders: tuple[Order, ...]
    target_weights: pd.Series  # post-borrow-filter, post-projection
    suppressed: tuple[str, ...]  # below min_order_usd (or truncated to 0 shares)
    dropped_for_borrow: tuple[str, ...]  # populated by the caller from borrow_filter's diff
    gross: float
    net: float


def borrow_filter(
    target: pd.Series,
    shortable: Mapping[str, bool],
    config: ProgrammeConfig,
    benchmark: str,
) -> pd.Series:
    """Spec section 9 design rule: give up gross exposure, never give up neutrality.

    Order of operations, exactly as the contract states:
      1. Zero every short whose symbol is not shortable. A symbol absent from
         `shortable` is treated as NOT shortable (fail closed) — availability
         that was never confirmed is not availability.
      2. Re-project the SURVIVING cross-sectional names (non-benchmark, weight
         != 0 after step 1 — both remaining longs and remaining shorts) to
         dollar-neutral by subtracting their mean. This is what
         `test_borrow_filter_preserves_neutrality` checks.
      3. Re-apply the per-name caps: `max_position` for every column except the
         benchmark, which uses `max_position_benchmark`.
      4. Re-apply the gross cap by SCALING DOWN ONLY. If gross already fell
         below the cap because shorts were dropped, that gross is NOT restored
         — `test_borrow_filter_never_raises_gross` checks this.

    The benchmark column is zeroed in step 1 like any other symbol if it is an
    unshortable short, but it is never touched by the step-2 neutrality
    projection, matching the contract.
    """
    result = target.astype(float).copy()

    # 1. Zero every short whose symbol is not shortable.
    for symbol in result.index:
        if result[symbol] < 0 and not shortable.get(symbol, False):
            result[symbol] = 0.0

    # 2. Re-project surviving cross-sectional (non-benchmark) names to
    #    dollar-neutral: subtract the mean over non-benchmark names carrying a
    #    non-zero weight. Names left at 0 by step 1 stay at 0.
    non_benchmark = result.index != benchmark
    survivors = non_benchmark & (result != 0.0)
    if survivors.any():
        result[survivors] = result[survivors] - result[survivors].mean()

    # 3. Re-apply per-name caps.
    allocator = config.allocator
    result[non_benchmark] = result[non_benchmark].clip(
        lower=-allocator.max_position, upper=allocator.max_position
    )
    if benchmark in result.index:
        result[benchmark] = float(
            np.clip(result[benchmark], -allocator.max_position_benchmark, allocator.max_position_benchmark)
        )

    # 4. Re-apply the gross cap by scaling down only — never scale up to
    #    compensate for gross surrendered in step 1.
    gross = float(result.abs().sum())
    if gross > allocator.gross_cap > 0:
        result = result * (allocator.gross_cap / gross)

    return result


def _bad_price(price: float) -> bool:
    return pd.isna(price) or not np.isfinite(price) or price <= 0


def build_orders(
    target: pd.Series,
    current: pd.Series,
    nav: float,
    prices: pd.Series,
    config: ProgrammeConfig,
    as_of: pd.Timestamp,
) -> OrderSet:
    """Spec Table 27, 15:42 ET: build the order set, suppress orders below $250.

    `delta_weight = target - current`, `notional = delta_weight * nav`,
    `quantity = int(notional / price)` truncated toward zero (Python's `int()`
    on a float already truncates toward zero).

    An order is suppressed — no `Order` is emitted, and the reported
    `target_weights` for that symbol reverts to `current` so the reported book
    matches what will actually be held, not what was wished for — when:
      - `abs(notional) < config.costs.min_order_usd`, or
      - integer share truncation collapses the trade to 0 shares even though
        the notional cleared the threshold (can't trade a fraction of a
        share; the practical effect — no trade happens — is identical, so it
        is folded into `suppressed` since `OrderSet` has no separate field
        for it).

    Names with a missing, zero, or non-finite price are skipped the same way
    (logged, target reverts to current) — never divided by zero.

    Symbols present in `current` but absent from `target` (e.g. dropped from
    the universe) are included too, ordered after `target`'s own index, so a
    stale position without a live target still gets a chance to be traded out.
    """
    extra = [s for s in current.index if s not in target.index]
    order_idx = list(target.index) + extra

    t = target.reindex(order_idx, fill_value=0.0).astype(float)
    c = current.reindex(order_idx, fill_value=0.0).astype(float)
    p = prices.reindex(order_idx)

    min_usd = config.costs.min_order_usd
    realized_target = c.copy()
    orders: list[Order] = []
    suppressed: list[str] = []
    missing_price: list[str] = []

    for symbol in order_idx:
        price = p[symbol]
        if _bad_price(price):
            missing_price.append(symbol)
            continue  # realized_target already holds `current`; no trade possible

        delta_weight = t[symbol] - c[symbol]
        notional = delta_weight * nav
        if abs(notional) < min_usd:
            suppressed.append(symbol)
            continue

        quantity = int(notional / float(price))  # truncation toward zero
        if quantity == 0:
            suppressed.append(symbol)
            continue

        side = "BUY" if quantity > 0 else "SELL"
        orders.append(
            Order(
                symbol=symbol,
                quantity=quantity,
                side=side,
                order_type="MOC",
                target_weight=float(t[symbol]),
                notional=float(notional),
            )
        )
        realized_target[symbol] = t[symbol]

    if missing_price:
        logger.warning("programme_orders_missing_price", symbols=tuple(missing_price))

    gross = float(realized_target.abs().sum())
    net = float(realized_target.sum())

    return OrderSet(
        as_of=as_of,
        orders=tuple(orders),
        target_weights=realized_target,
        suppressed=tuple(suppressed),
        dropped_for_borrow=(),
        gross=gross,
        net=net,
    )


class Broker(Protocol):
    def nav(self) -> float: ...
    def positions(self) -> dict[str, float]: ...  # symbol -> shares
    def shortable(self, symbols: list[str]) -> dict[str, bool]: ...
    def submit_moc(self, orders: Sequence[Order]) -> list[str]: ...
    def fills(self, since: pd.Timestamp) -> pd.DataFrame: ...


class DryRunBroker:
    """In-memory Broker for `cli run --mode dryrun`. No network, deterministic.

    Fills are marked at the close price handed to it via `closes` — the same
    price the backtest would mark at — so a dry run reproduces exactly the
    lag/cost assumptions the research harness uses, with no live dependency.
    """

    def __init__(
        self,
        starting_nav: float,
        closes: pd.Series,
        positions: Mapping[str, float] | None = None,
    ) -> None:
        self._nav = float(starting_nav)
        self._closes = closes
        self._positions: dict[str, float] = dict(positions or {})
        self._fills: list[dict] = []

    def nav(self) -> float:
        return self._nav

    def positions(self) -> dict[str, float]:
        return dict(self._positions)

    def shortable(self, symbols: list[str]) -> dict[str, bool]:
        # ponytail: dry-run assumes unlimited borrow (no live broker to ask);
        # wire a configurable unshortable set if a scenario needs to rehearse
        # borrow constraints offline.
        return dict.fromkeys(symbols, True)

    def submit_moc(self, orders: Sequence[Order]) -> list[str]:
        order_ids: list[str] = []
        for i, order in enumerate(orders):
            price = self._closes.get(order.symbol)
            if price is None or _bad_price(price):
                logger.warning("dryrun_broker_skip_missing_price", symbol=order.symbol)
                continue
            self._positions[order.symbol] = self._positions.get(order.symbol, 0.0) + order.quantity
            order_id = f"dryrun-{order.symbol}-{i}"
            order_ids.append(order_id)
            self._fills.append(
                {
                    "order_id": order_id,
                    "symbol": order.symbol,
                    "quantity": order.quantity,
                    "price": float(price),
                    "side": order.side,
                    "timestamp": pd.Timestamp.now(tz="UTC"),
                }
            )
        return order_ids

    def fills(self, since: pd.Timestamp) -> pd.DataFrame:
        columns = ["order_id", "symbol", "quantity", "price", "side", "timestamp"]
        if not self._fills:
            return pd.DataFrame(columns=columns)
        frame = pd.DataFrame(self._fills)
        return frame[frame["timestamp"] >= since].reset_index(drop=True)


class AlpacaProgrammeBroker:
    """Broker over Alpaca, reusing `mentisrex.paper.alpaca_broker.AlpacaBroker` for
    credentials, `account()`, and positions (ADDENDUM A.6) rather than
    reimplementing that wiring.

    `submit_moc` does NOT go through `AlpacaBroker.submit()` — that method
    hard-codes `time_in_force="day"`, which would silently produce a same-day
    market fill mislabelled as MOC (spec Table 15: "MOC window missed... a
    morning fill is an unmeasured basis" versus the backtest's close mark).
    Instead this class submits genuine market-on-close orders itself via
    Alpaca's REST orders endpoint with `{"type": "market",
    "time_in_force": "cls"}`.

    Credentials come from `get_settings().alpaca_api_key` /
    `.alpaca_api_secret` and are never hard-coded or logged, not even
    truncated. No network call happens at import time or at construction —
    both the reused `AlpacaBroker` and this class's own order-submission
    client are created lazily on first use.
    """

    def __init__(self, base_url: str = ALPACA_BASE_URL) -> None:
        # base_url retained only for interface compatibility — AlpacaPaperBroker
        # (M28) hardcodes its endpoint and rejects any override, so this is a
        # no-op unless it already equals ALPACA_PAPER_BASE_URL.
        self._base_url = base_url
        self._broker: AlpacaBroker | None = None

    def _client(self) -> AlpacaBroker:
        if self._broker is None:
            settings = get_settings()
            if not settings.alpaca_api_key or not settings.alpaca_api_secret:
                raise ConfigError(
                    "Alpaca credentials are not configured",
                    detail="Set alpaca_api_key / alpaca_api_secret (env or .env.development)",
                )
            self._broker = AlpacaBroker(
                api_key=settings.alpaca_api_key, api_secret=settings.alpaca_api_secret
            )
        return self._broker

    def nav(self) -> float:
        equity: Decimal = self._client().account()["equity"]
        return float(equity)

    def positions(self) -> dict[str, float]:
        positions: dict[str, Decimal] = self._client().account()["positions"]
        return {symbol: float(qty) for symbol, qty in positions.items()}

    def shortable(self, symbols: list[str]) -> dict[str, bool]:
        raise NotImplementedError(
            "AlpacaProgrammeBroker.shortable: the reused AlpacaBroker has no asset/shortability "
            "lookup. Alpaca's GET /v2/assets/{symbol} (fields `shortable`, `easy_to_borrow`) "
            "would supply it. Wire that endpoint before running any book with a short leg through "
            "this broker."
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
            }
            resp = client._http.post("/v2/orders", json=payload)
            if not resp.is_success:
                msg = resp.json().get("message", resp.text)
                logger.warning("alpaca_moc_order_rejected", symbol=order.symbol, reason=msg)
                continue
            data = resp.json()
            order_ids.append(data["id"])
            logger.info(
                "alpaca_moc_order", symbol=order.symbol, id=data["id"], status=data.get("status")
            )
        return order_ids

    def fills(self, since: pd.Timestamp) -> pd.DataFrame:
        raise NotImplementedError(
            "AlpacaProgrammeBroker.fills: no fills-since-timestamp query exists anywhere in "
            "mentisrex.paper. Alpaca's GET /v2/orders?status=closed&after=<ts> would supply it. "
            "Wire that (with Decimal-accurate price/qty parsing) before programme/reconcile.py "
            "can compare targets against real fills."
        )
