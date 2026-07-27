"""RiskEngine — the pre-trade gatekeeper. Strategy -> RiskEngine -> Execution.

Every proposed order passes through evaluate() and comes back APPROVE / MODIFY /
REJECT. No strategy bypasses it: execution must act on the verdict, never on the
raw order. Capital preservation is the only objective here.

Decision policy (checked in order; first hard breach rejects):
  - kill switch tripped                    -> REJECT everything until reset()
  - daily loss / drawdown breach           -> REJECT + trip kill switch
  - position size / leverage / liquidity /
    single-trade loss-to-stop              -> MODIFY qty down to the binding cap

MODIFY clamps to the *smallest* quantity any single check allows, so the emitted
order satisfies all of them at once. A clamp to zero becomes a REJECT. Per-name
concentration IS the position-size cap; portfolio HHI/sector concentration is
measured in the monitor, not gated here. Math for each rule is inline below.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aurelius.backtesting.portfolio.state import PortfolioState
from aurelius.core.logging import get_logger
from aurelius.risk.models import RiskLimits, RiskVerdict

logger = get_logger(__name__)


@dataclass
class OrderContext:
    """What the engine needs to judge one order beyond the portfolio state.

    price       : current mark for the symbol (Decimal)
    quantity    : proposed order quantity, always positive
    is_buy      : True adds exposure; a reducing/closing trade skips size caps
    adv         : average daily volume (shares); None disables the liquidity check
    stop_price  : protective stop; enables the single-trade max-loss check
    daily_pnl   : realized+unrealized P&L so far today (currency)
    sod_equity  : start-of-day equity for the daily-loss ratio; None -> NAV
    """

    symbol: str
    price: Decimal
    quantity: Decimal
    is_buy: bool
    adv: Decimal | None = None
    stop_price: Decimal | None = None
    daily_pnl: Decimal = Decimal("0")
    sod_equity: Decimal | None = None


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self._limits = limits or RiskLimits()
        self._halted = False
        self._halt_reason = ""

    @property
    def is_halted(self) -> bool:
        return self._halted

    def reset(self) -> None:
        """Clear the emergency shutdown. A human risk officer's re-enable."""
        self._halted = False
        self._halt_reason = ""

    def trip(self, reason: str) -> None:
        """Emergency shutdown: reject-all until reset()."""
        if not self._halted:
            logger.warning("risk_kill_switch", reason=reason)
        self._halted = True
        self._halt_reason = reason

    def evaluate(self, ctx: OrderContext, state: PortfolioState) -> RiskVerdict:
        lim = self._limits
        nav = state.total_value

        # 0. Kill switch already tripped -> nothing gets through.
        if self._halted:
            return RiskVerdict.reject(f"kill switch active: {self._halt_reason}")

        if ctx.price <= 0 or nav <= 0:
            return RiskVerdict.reject("no price / non-positive NAV")

        # 1. Daily loss limit + drawdown -> account-level shutdown.
        #    breach if daily_pnl <= -daily_loss_limit * SOD_equity
        sod = ctx.sod_equity if ctx.sod_equity and ctx.sod_equity > 0 else nav
        if ctx.daily_pnl <= -lim.daily_loss_limit * sod:
            self.trip(f"daily loss {ctx.daily_pnl / sod:.1%} <= -{lim.daily_loss_limit:.1%}")
            return RiskVerdict.reject(self._halt_reason)
        #    drawdown = (NAV - peak) / peak ; breach if worse than -halt
        dd = state.drawdown
        if dd < -lim.max_drawdown_halt:
            self.trip(f"drawdown {dd:.1%} < -{lim.max_drawdown_halt:.1%}")
            return RiskVerdict.reject(self._halt_reason)

        # Reducing/closing trades never worsen risk -> approve straight through.
        if not ctx.is_buy and not self._is_increasing(ctx, state):
            return RiskVerdict.approve()

        # 2. Quantity-clamping checks: take the tightest cap across all of them.
        #    Per-name concentration is the position-size cap (weight of NAV);
        #    portfolio-level concentration (HHI, sector) lives in the monitor.
        qmax = ctx.quantity
        reasons: list[str] = []
        for cap, why in self._quantity_caps(ctx, state):
            if cap < qmax:
                qmax = cap
                reasons.append(why)

        if qmax <= 0:
            return RiskVerdict.reject("; ".join(reasons) or "order clamped to zero")
        if qmax < ctx.quantity:
            return RiskVerdict.modify(qmax, "; ".join(reasons))
        return RiskVerdict.approve()

    # ── individual rules ──────────────────────────────────────────────────────

    def _is_increasing(self, ctx: OrderContext, state: PortfolioState) -> bool:
        """A sell that flips a position larger short *increases* exposure."""
        pos = state.positions.get(ctx.symbol)
        cur = pos.quantity if pos else Decimal("0")
        return cur <= 0  # already short/flat and selling more -> growing short

    def _quantity_caps(
        self, ctx: OrderContext, state: PortfolioState
    ) -> list[tuple[Decimal, str]]:
        """Every check that can be satisfied by shrinking quantity.

        Each yields the max quantity it permits; evaluate() takes the min.
        """
        lim = self._limits
        nav = state.total_value
        p = ctx.price
        caps: list[tuple[Decimal, str]] = []

        # Position size: w = |q*p|/NAV <= max_position_pct  =>  q <= max_pct*NAV/p
        pos = state.positions.get(ctx.symbol)
        cur_mv = abs(pos.market_value) if pos else Decimal("0")
        allowed_mv = lim.max_position_pct * nav - cur_mv
        caps.append((self._floor(allowed_mv / p),
                     f"position size cap {lim.max_position_pct:.0%} NAV"))

        # Gross leverage: (gross + q*p)/NAV <= max_gross_leverage
        headroom = lim.max_gross_leverage * nav - state.gross_exposure
        caps.append((self._floor(headroom / p), f"gross leverage cap {lim.max_gross_leverage}x"))

        # Liquidity: q <= max_participation_pct * ADV
        if ctx.adv is not None and ctx.adv > 0:
            caps.append((self._floor(lim.max_participation_pct * ctx.adv),
                         f"liquidity cap {lim.max_participation_pct:.0%} ADV"))

        # Single-trade max loss: |p - stop| * q <= single_trade_max_loss_pct * NAV
        if ctx.stop_price is not None:
            risk_per_share = abs(p - ctx.stop_price)
            if risk_per_share > 0:
                budget = lim.single_trade_max_loss_pct * nav
                caps.append((self._floor(budget / risk_per_share),
                             f"stop-loss budget {lim.single_trade_max_loss_pct:.0%} NAV"))
        return caps

    @staticmethod
    def _floor(x: Decimal) -> Decimal:
        """Whole shares, never negative."""
        return max(Decimal("0"), Decimal(int(x)))
