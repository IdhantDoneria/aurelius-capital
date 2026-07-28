"""Trading data repositories: orders, fills, positions, P&L.

Order state machine transitions are enforced here, not in the model.
The repository is the enforcement point for business rules that span
multiple reads + writes in a single transaction.

Position accounting uses FIFO lot matching for realized P&L computation.
This is the most common method for US equity taxation; override for LIFO if needed.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, select

from aurelius.core.errors import DomainError, NotFoundError
from aurelius.core.logging import get_logger
from aurelius.infrastructure.database.models.trading import (
    Fill,
    Order,
    PnLSnapshot,
    Position,
)
from aurelius.infrastructure.database.repositories.base import BaseRepository

logger = get_logger(__name__)

# Valid state transitions for the order state machine
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"submitted", "cancelled", "rejected"},
    "submitted": {"acknowledged", "partial", "filled", "cancelled", "rejected", "expired"},
    "acknowledged": {"partial", "filled", "cancelled", "rejected", "expired"},
    "partial": {"filled", "cancelled"},
    "filled": set(),  # terminal
    "cancelled": set(),  # terminal
    "rejected": set(),  # terminal
    "expired": set(),  # terminal
}


class OrderRepository(BaseRepository[Order]):
    model_class = Order

    async def get_by_id(self, id: UUID) -> Order | None:
        """Override: orders are partitioned, scalar get needs timestamp.
        Use get_by_broker_id or get_active_for_account for efficient lookups.
        """
        result = await self._session.execute(select(Order).where(Order.id == id).limit(1))
        return result.scalar_one_or_none()

    async def get_active_for_account(self, account_id: UUID) -> list[Order]:
        """Return all open orders for an account.
        Uses partial index ix_orders_active — very fast.
        """
        result = await self._session.execute(
            select(Order)
            .where(
                and_(
                    Order.account_id == account_id,
                    Order.status.in_(["pending", "submitted", "acknowledged", "partial"]),
                )
            )
            .order_by(Order.submitted_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_broker_id(self, broker_order_id: str) -> Order | None:
        """Look up by broker's reference ID. Used when processing fill callbacks."""
        result = await self._session.execute(
            select(Order).where(Order.broker_order_id == broker_order_id).limit(1)
        )
        return result.scalar_one_or_none()

    async def transition_status(
        self,
        order_id: UUID,
        submitted_at: datetime,
        new_status: str,
        **updates: object,
    ) -> Order:
        """Apply a state machine transition. Raises if transition is invalid.

        Always pass submitted_at so PostgreSQL can route to the correct partition.
        Without it, the query scans all partitions.
        """
        result = await self._session.execute(
            select(Order).where(and_(Order.id == order_id, Order.submitted_at == submitted_at))
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise NotFoundError(f"Order {order_id} not found")

        current = order.status
        if new_status not in _VALID_TRANSITIONS.get(current, set()):
            raise DomainError(
                f"Invalid order status transition: {current} → {new_status}",
                detail=f"Order {order_id}",
            )

        order.status = new_status  # type: ignore[assignment]
        for field, value in updates.items():
            setattr(order, field, value)

        await self._session.flush()
        logger.info(
            "order_status_transition",
            order_id=str(order_id),
            from_status=current,
            to_status=new_status,
        )
        return order

    async def apply_fill(
        self,
        order_id: UUID,
        submitted_at: datetime,
        fill_quantity: Decimal,
        fill_price: Decimal,
    ) -> Order:
        """Update order fill state after a fill event.

        Recomputes avg_fill_price using weighted average formula.
        Transitions order to 'partial' or 'filled' based on remaining qty.
        """
        result = await self._session.execute(
            select(Order).where(and_(Order.id == order_id, Order.submitted_at == submitted_at))
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise NotFoundError(f"Order {order_id} not found")

        if order.status not in ("submitted", "acknowledged", "partial"):
            raise DomainError(f"Cannot apply fill to order in status {order.status!r}")

        # Weighted average fill price
        prev_notional = (order.avg_fill_price or Decimal(0)) * order.filled_quantity
        new_notional = fill_price * fill_quantity
        new_filled_qty = order.filled_quantity + fill_quantity
        order.avg_fill_price = (prev_notional + new_notional) / new_filled_qty
        order.filled_quantity = new_filled_qty

        now = datetime.now(UTC)
        if order.first_fill_at is None:
            order.first_fill_at = now

        if order.filled_quantity >= order.quantity:
            order.status = "filled"  # type: ignore[assignment]
            order.filled_at = now
        else:
            order.status = "partial"  # type: ignore[assignment]

        await self._session.flush()
        return order


class FillRepository(BaseRepository[Fill]):
    model_class = Fill

    async def get_fills_for_order(self, order_id: UUID) -> list[Fill]:
        result = await self._session.execute(
            select(Fill).where(Fill.order_id == order_id).order_by(Fill.timestamp.asc())
        )
        return list(result.scalars().all())

    async def get_fills_for_account(
        self,
        account_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[Fill]:
        """All fills for an account in a date range. Used for P&L attribution."""
        result = await self._session.execute(
            select(Fill)
            .where(
                and_(
                    Fill.account_id == account_id,
                    Fill.timestamp >= start,
                    Fill.timestamp < end,
                )
            )
            .order_by(Fill.timestamp.asc())
        )
        return list(result.scalars().all())

    async def get_pending_settlement(self, settlement_date: datetime) -> list[Fill]:
        """Returns fills settling on or before given date. For settlement reconciliation."""
        result = await self._session.execute(
            select(Fill).where(Fill.settlement_date <= settlement_date)
        )
        return list(result.scalars().all())

    async def total_commission_for_period(
        self, account_id: UUID, start: datetime, end: datetime
    ) -> Decimal:
        result = await self._session.execute(
            select(func.sum(Fill.commission)).where(
                and_(
                    Fill.account_id == account_id,
                    Fill.timestamp >= start,
                    Fill.timestamp < end,
                )
            )
        )
        return result.scalar_one() or Decimal(0)


class PositionRepository(BaseRepository[Position]):
    model_class = Position

    async def get_open_position(
        self,
        account_id: UUID,
        symbol_id: UUID,
        strategy_id: UUID | None = None,
    ) -> Position | None:
        """Return current open position. Uses partial index for efficiency."""
        query = select(Position).where(
            and_(
                Position.account_id == account_id,
                Position.symbol_id == symbol_id,
                Position.closed_at.is_(None),
            )
        )
        if strategy_id is not None:
            query = query.where(Position.strategy_id == strategy_id)

        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_open_positions_for_account(self, account_id: UUID) -> list[Position]:
        """All open positions for an account. Risk system calls this frequently."""
        result = await self._session.execute(
            select(Position)
            .where(
                and_(
                    Position.account_id == account_id,
                    Position.closed_at.is_(None),
                )
            )
            .order_by(Position.symbol_id)
        )
        return list(result.scalars().all())

    async def apply_fill_to_position(
        self,
        account_id: UUID,
        symbol_id: UUID,
        strategy_id: UUID | None,
        fill_quantity: Decimal,
        fill_price: Decimal,
        side: str,
    ) -> Position:
        """Update or create position after a fill. Core accounting logic.

        BUY: increases long position or reduces short position.
        SELL/SELL_SHORT: reduces long or increases short.
        Realized P&L computed on position reduces (FIFO lot matching is done
        at a higher level — here we use weighted average cost basis).
        """
        position = await self.get_open_position(account_id, symbol_id, strategy_id)

        signed_qty = fill_quantity if side in ("buy", "buy_to_cover") else -fill_quantity

        if position is None:
            # New position
            position = Position(
                account_id=account_id,
                symbol_id=symbol_id,
                strategy_id=strategy_id,
                quantity=signed_qty,
                avg_cost=fill_price,
                cost_basis=abs(signed_qty) * fill_price,
                realized_pnl=Decimal(0),
                opened_at=datetime.now(UTC),
            )
            self._session.add(position)
        else:
            prev_qty = position.quantity
            new_qty = prev_qty + signed_qty

            if prev_qty * signed_qty >= 0:
                # Same direction: weighted average cost
                total_cost = (abs(prev_qty) * position.avg_cost) + (abs(signed_qty) * fill_price)
                position.avg_cost = total_cost / abs(new_qty)
            else:
                # Reducing position: realize P&L on the closed portion
                closed_qty = min(abs(signed_qty), abs(prev_qty))
                if prev_qty > 0:
                    realized = (fill_price - position.avg_cost) * closed_qty
                else:
                    realized = (position.avg_cost - fill_price) * closed_qty
                position.realized_pnl += realized

            position.quantity = new_qty
            position.cost_basis = abs(new_qty) * position.avg_cost

            if new_qty == 0:
                position.closed_at = datetime.now(UTC)

        position.last_updated_at = datetime.now(UTC)
        await self._session.flush()
        logger.info(
            "position_updated",
            account_id=str(account_id),
            symbol_id=str(symbol_id),
            quantity=str(position.quantity),
            avg_cost=str(position.avg_cost),
        )
        return position

    async def mark_to_market(self, account_id: UUID, prices: dict[UUID, Decimal]) -> list[Position]:
        """Update unrealized P&L for all open positions given current prices.
        Call at end of day or on price updates.
        """
        positions = await self.get_open_positions_for_account(account_id)
        updated = []
        for pos in positions:
            price = prices.get(pos.symbol_id)
            if price is not None:
                pos.last_price = price
                pos.unrealized_pnl = (price - pos.avg_cost) * pos.quantity
                pos.last_updated_at = datetime.now(UTC)
                updated.append(pos)
        await self._session.flush()
        return updated

    async def get_portfolio_exposure(self, account_id: UUID) -> dict:
        """Compute gross/net exposure. Used by risk system."""
        result = await self._session.execute(
            select(
                func.sum(Position.last_price * Position.quantity).label("net_market_value"),
                func.sum(func.abs(Position.last_price * Position.quantity)).label(
                    "gross_market_value"
                ),
                func.count().label("position_count"),
            ).where(
                and_(
                    Position.account_id == account_id,
                    Position.closed_at.is_(None),
                    Position.last_price.is_not(None),
                )
            )
        )
        row = result.one()
        return {
            "net_market_value": row.net_market_value or Decimal(0),
            "gross_market_value": row.gross_market_value or Decimal(0),
            "position_count": row.position_count,
        }


class PnLSnapshotRepository(BaseRepository[PnLSnapshot]):
    model_class = PnLSnapshot

    async def get_latest(
        self, account_id: UUID, strategy_id: UUID | None = None
    ) -> PnLSnapshot | None:
        query = select(PnLSnapshot).where(PnLSnapshot.account_id == account_id)
        if strategy_id is not None:
            query = query.where(PnLSnapshot.strategy_id == strategy_id)
        query = query.order_by(PnLSnapshot.snapshot_at.desc()).limit(1)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_equity_curve(
        self,
        account_id: UUID,
        start: datetime,
        end: datetime,
        strategy_id: UUID | None = None,
    ) -> list[PnLSnapshot]:
        """Return the equity curve (time series of total equity) for performance analysis."""
        query = select(PnLSnapshot).where(
            and_(
                PnLSnapshot.account_id == account_id,
                PnLSnapshot.snapshot_at >= start,
                PnLSnapshot.snapshot_at < end,
            )
        )
        if strategy_id is not None:
            query = query.where(PnLSnapshot.strategy_id == strategy_id)
        query = query.order_by(PnLSnapshot.snapshot_at.asc())
        result = await self._session.execute(query)
        return list(result.scalars().all())
