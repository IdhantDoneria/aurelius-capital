"""Trading data models: accounts, strategies, orders, fills, positions, P&L, risk.

CRITICAL DESIGN CONSTRAINTS:
1. fills.order_id is NOT a FK — cross-partition FK is not supported in PostgreSQL.
   Referential integrity enforced at application (repository) layer.
2. Orders are partitioned by submitted_at — the PK is (id, submitted_at).
3. Positions table is NOT partitioned — it's a current-state snapshot, not time-series.
4. Partial index on orders WHERE status IN ('pending','submitted','partial') for
   active order dashboard queries.

ORDER STATE MACHINE:
pending → submitted → partial → filled
                    ↘ cancelled
                    ↘ rejected
submitted → expired (day order past close)

Never delete orders or fills. Audit trail is permanent.
"""

import enum as pyenum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mentisrex.infrastructure.database.models.base import (
    Base,
    Notional,
    Price,
    Quantity,
    Ratio,
    TimestampMixin,
)


class OrderTypeEnum(pyenum.Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TWAP = "twap"
    VWAP = "vwap"
    POV = "pov"  # Percentage of Volume
    IMPLEMENTATION_SHORTFALL = "is"


class OrderSideEnum(pyenum.Enum):
    BUY = "buy"
    SELL = "sell"
    SELL_SHORT = "sell_short"
    BUY_TO_COVER = "buy_to_cover"


class OrderStatusEnum(pyenum.Enum):
    PENDING = "pending"  # created locally, not yet submitted to broker
    SUBMITTED = "submitted"  # sent to broker, awaiting ack
    ACKNOWLEDGED = "acknowledged"  # broker confirmed receipt
    PARTIAL = "partial"  # partially filled
    FILLED = "filled"  # fully filled
    CANCELLED = "cancelled"  # cancelled before fill
    REJECTED = "rejected"  # rejected by broker or risk
    EXPIRED = "expired"  # day order expired at close


class TimeInForceEnum(pyenum.Enum):
    DAY = "day"
    GTC = "gtc"  # Good Till Cancelled
    IOC = "ioc"  # Immediate or Cancel
    FOK = "fok"  # Fill or Kill
    GTD = "gtd"  # Good Till Date


class AccountTypeEnum(pyenum.Enum):
    LIVE = "live"
    PAPER = "paper"
    MARGIN = "margin"
    CASH = "cash"
    IRA = "ira"


class RiskEventTypeEnum(pyenum.Enum):
    POSITION_LIMIT_BREACH = "position_limit_breach"
    DRAWDOWN_LIMIT = "drawdown_limit"
    VAR_BREACH = "var_breach"
    SECTOR_CONCENTRATION = "sector_concentration"
    MARGIN_CALL = "margin_call"
    KILL_SWITCH = "kill_switch_triggered"
    CIRCUIT_BREAKER = "circuit_breaker"
    LOSS_LIMIT_DAILY = "loss_limit_daily"


class RiskSeverityEnum(pyenum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    FATAL = "fatal"  # triggers kill switch


class Account(Base, TimestampMixin):
    """Trading account. One platform can manage multiple accounts/brokers."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    broker: Mapped[str] = mapped_column(String(50), nullable=False)
    account_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    account_type: Mapped[str] = mapped_column(
        Enum(AccountTypeEnum, name="account_type_enum"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Strategy(Base, TimestampMixin):
    """Trading strategy definition. Versioned — never mutate, create new version."""

    __tablename__ = "strategies"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_strategy_name_version"),
        Index("ix_strategy_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="Full strategy config snapshot. Immutable after activation.",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"Strategy(name={self.name!r}, v{self.version}, active={self.is_active})"


class Order(Base):
    """Order record. Partitioned monthly by submitted_at.

    PK is (id, submitted_at) — required by PostgreSQL partitioning.
    UUID id provides stable cross-system identity for fills reconciliation.

    parent_order_id: for algorithmic orders that spawn child slice orders
    (e.g., a TWAP order creates many child limit orders at each interval).

    broker_order_id: broker's reference ID. Used to match fill messages
    from broker callbacks. Not unique globally — same broker may reuse IDs
    across sessions, so (broker_order_id, submitted_at date) is the real key.
    """

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_account_status_ts", "account_id", "status", "submitted_at"),
        Index("ix_orders_strategy_status_ts", "strategy_id", "status", "submitted_at"),
        Index("ix_orders_symbol_ts", "symbol_id", "submitted_at"),
        Index(
            "ix_orders_active",
            "status",
            "submitted_at",
            postgresql_where=text("status IN ('pending', 'submitted', 'acknowledged', 'partial')"),
        ),
        Index(
            "ix_orders_broker_id",
            "broker_order_id",
            postgresql_where=text("broker_order_id IS NOT NULL"),
        ),
        CheckConstraint("filled_quantity >= 0", name="ck_orders_filled_qty_nonneg"),
        CheckConstraint("quantity > 0", name="ck_orders_qty_positive"),
        {
            "postgresql_partition_by": "RANGE (submitted_at)",
            "comment": "Partitioned monthly. PK includes submitted_at per PostgreSQL requirement.",
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        nullable=False,
        comment="Partition key. Time order was submitted to broker.",
    )

    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    symbol_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    order_type: Mapped[str] = mapped_column(
        Enum(OrderTypeEnum, name="order_type_enum"), nullable=False
    )
    side: Mapped[str] = mapped_column(Enum(OrderSideEnum, name="order_side_enum"), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Price, nullable=True)
    stop_price: Mapped[Decimal | None] = mapped_column(Price, nullable=True)
    time_in_force: Mapped[str] = mapped_column(
        Enum(TimeInForceEnum, name="time_in_force_enum"),
        nullable=False,
        server_default="day",
    )
    good_till_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # State
    status: Mapped[str] = mapped_column(
        Enum(OrderStatusEnum, name="order_status_enum"),
        nullable=False,
        server_default="pending",
    )
    filled_quantity: Mapped[Decimal] = mapped_column(
        Quantity, nullable=False, server_default=text("0")
    )
    avg_fill_price: Mapped[Decimal | None] = mapped_column(Price, nullable=True)

    # Broker integration
    broker_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Lifecycle timestamps
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_fill_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Algo order hierarchy
    parent_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="For child slice orders spawned by TWAP/VWAP parent",
    )

    extra_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, name="metadata", nullable=False, server_default=text("'{}'::jsonb")
    )

    @property
    def remaining_quantity(self) -> Decimal:
        return self.quantity - self.filled_quantity

    @property
    def fill_rate(self) -> Decimal:
        if self.quantity == 0:
            return Decimal(0)
        return self.filled_quantity / self.quantity

    def __repr__(self) -> str:
        return (
            f"Order(id={self.id}, symbol={self.symbol_id}, "
            f"side={self.side}, qty={self.quantity}, status={self.status})"
        )


class Fill(Base):
    """Individual execution fill. Append-only. Partitioned monthly by timestamp.

    IMMUTABLE after creation. Fills are the permanent record of trades.
    Never update, never delete.

    notional_value = price x quantity (in account currency).
    Stored explicitly because price x quantity needs to be computed at fill time
    using the exact fill price, not reconstructed later.

    execution_latency_ms: time from order submission to fill receipt.
    Critical for TCA (Transaction Cost Analysis) — high latency = more slippage.
    """

    __tablename__ = "fills"
    __table_args__ = (
        Index("ix_fills_order_ts", "order_id", "timestamp"),
        Index("ix_fills_account_ts", "account_id", "timestamp"),
        Index("ix_fills_symbol_ts", "symbol_id", "timestamp"),
        Index("ix_fills_settlement", "settlement_date"),
        Index(
            "ix_fills_broker_fill_id",
            "broker_fill_id",
            postgresql_where=text("broker_fill_id IS NOT NULL"),
        ),
        UniqueConstraint(
            "broker_fill_id",
            name="uq_fills_broker_fill_id",
        ),
        CheckConstraint("price > 0", name="ck_fills_price_positive"),
        CheckConstraint("quantity > 0", name="ck_fills_qty_positive"),
        {
            "postgresql_partition_by": "RANGE (timestamp)",
            "comment": (
                "Immutable audit trail. Partitioned monthly. "
                "order_id is NOT a FK — cross-partition FKs unsupported in PostgreSQL."
            ),
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        nullable=False,
        comment="Exact fill time from exchange or broker",
    )

    # order_id deliberately NOT FK — see module docstring
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="References orders.id. Not FK due to partition constraint.",
    )
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    symbol_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    side: Mapped[str] = mapped_column(Enum(OrderSideEnum, name="order_side_enum"), nullable=False)
    price: Mapped[Decimal] = mapped_column(Price, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity, nullable=False)
    notional_value: Mapped[Decimal] = mapped_column(
        Notional,
        nullable=False,
        comment="price x quantity in account currency. Stored explicitly for TCA.",
    )
    commission: Mapped[Decimal] = mapped_column(Notional, nullable=False, server_default=text("0"))
    commission_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="USD"
    )

    exchange: Mapped[str | None] = mapped_column(String(20), nullable=True)
    settlement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    broker_fill_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    execution_latency_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Order submission to fill receipt. Used in TCA.",
    )
    extra_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, name="metadata", nullable=False, server_default=text("'{}'::jsonb")
    )

    def __repr__(self) -> str:
        return f"Fill(order={self.order_id}, price={self.price}, qty={self.quantity})"


class Position(Base, TimestampMixin):
    """Current portfolio position. NOT partitioned — current state only.

    quantity < 0 = short position.
    avg_cost: weighted average cost basis per share.
    cost_basis: total cost basis = quantity x avg_cost (absolute value for shorts).
    realized_pnl: accumulated from closed partial lots.
    unrealized_pnl: mark-to-market, updated on price tick or end of day.

    The unique constraint allows only ONE open position per (account, strategy, symbol).
    When fully closed, closed_at is set and the position becomes historical.
    A new position opening the same symbol creates a new row.

    is_open: generated column — true when quantity != 0.
    """

    __tablename__ = "positions"
    __table_args__ = (
        # Partial unique index uq_positions_open defined in migration DDL
        # (UniqueConstraint doesn't support WHERE clause — use Index instead)
        Index(
            "ix_positions_account_open",
            "account_id",
            postgresql_where=text("closed_at IS NULL"),
        ),
        Index(
            "ix_positions_strategy_open",
            "strategy_id",
            postgresql_where=text("closed_at IS NULL"),
        ),
        Index(
            "ix_positions_symbol_open",
            "symbol_id",
            postgresql_where=text("closed_at IS NULL"),
        ),
        CheckConstraint("avg_cost > 0", name="ck_positions_avg_cost_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    symbol_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(
        Quantity,
        nullable=False,
        comment="Shares held. Negative = short.",
    )
    avg_cost: Mapped[Decimal] = mapped_column(
        Price,
        nullable=False,
        comment="Weighted average cost per share",
    )
    cost_basis: Mapped[Decimal] = mapped_column(
        Notional,
        nullable=False,
        comment="Total cost basis = |quantity| x avg_cost",
    )
    realized_pnl: Mapped[Decimal] = mapped_column(
        Notional,
        nullable=False,
        server_default=text("0"),
        comment="Accumulated realized P&L from partial closes",
    )
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(
        Notional,
        nullable=True,
        comment="Mark-to-market P&L. Updated on price tick or EOD.",
    )
    last_price: Mapped[Decimal | None] = mapped_column(Price, nullable=True)
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def market_value(self) -> Decimal | None:
        if self.last_price is None:
            return None
        return self.quantity * self.last_price

    def __repr__(self) -> str:
        return f"Position(symbol={self.symbol_id}, qty={self.quantity}, avg_cost={self.avg_cost})"


class PnLSnapshot(Base):
    """Point-in-time P&L and exposure snapshot. Partitioned monthly.

    Written at end-of-day (and intraday for live systems).
    The time-series of these rows is the equity curve.
    Sharpe, drawdown, etc. are computed from this table.

    Exposure breakdown:
    - gross_exposure = long_market_value + |short_market_value|
    - net_exposure = long_market_value - |short_market_value|
    - leverage = gross_exposure / total_equity
    """

    __tablename__ = "pnl_snapshots"
    __table_args__ = (
        Index("ix_pnl_account_ts", "account_id", "snapshot_at"),
        Index("ix_pnl_strategy_ts", "strategy_id", "snapshot_at"),
        {"postgresql_partition_by": "RANGE (snapshot_at)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )

    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Balance sheet
    total_equity: Mapped[Decimal] = mapped_column(Notional, nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(Notional, nullable=False)
    long_market_value: Mapped[Decimal] = mapped_column(Notional, nullable=False)
    short_market_value: Mapped[Decimal] = mapped_column(Notional, nullable=False)
    gross_exposure: Mapped[Decimal] = mapped_column(Notional, nullable=False)
    net_exposure: Mapped[Decimal] = mapped_column(Notional, nullable=False)
    leverage: Mapped[Decimal] = mapped_column(Ratio, nullable=False)

    # P&L breakdown
    realized_pnl_daily: Mapped[Decimal] = mapped_column(Notional, nullable=False)
    realized_pnl_mtd: Mapped[Decimal] = mapped_column(Notional, nullable=False)
    realized_pnl_ytd: Mapped[Decimal] = mapped_column(Notional, nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Notional, nullable=False)
    total_pnl_daily: Mapped[Decimal] = mapped_column(Notional, nullable=False)
    total_commission_daily: Mapped[Decimal] = mapped_column(Notional, nullable=False)

    # Risk metrics (trailing, computed at snapshot time)
    sharpe_ratio_trailing: Mapped[Decimal | None] = mapped_column(Ratio, nullable=True)
    max_drawdown_trailing: Mapped[Decimal | None] = mapped_column(Ratio, nullable=True)
    var_95_daily: Mapped[Decimal | None] = mapped_column(
        Notional,
        nullable=True,
        comment="Value at Risk 95% confidence, 1-day horizon",
    )
    position_count: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class RiskEvent(Base):
    """Risk limit breach or system risk event. Permanent audit record.

    When severity=FATAL: kill switch triggered, all orders cancelled.
    resolved_at: when the breach was cleared (position reduced, limit adjusted, etc.).
    NULL resolved_at = still breached.
    """

    __tablename__ = "risk_events"
    __table_args__ = (
        Index("ix_risk_account_triggered", "account_id", "triggered_at"),
        Index("ix_risk_unresolved", "triggered_at", postgresql_where=text("resolved_at IS NULL")),
        Index("ix_risk_severity", "severity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    strategy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    event_type: Mapped[str] = mapped_column(
        Enum(RiskEventTypeEnum, name="risk_event_type_enum"), nullable=False
    )
    severity: Mapped[str] = mapped_column(
        Enum(RiskSeverityEnum, name="risk_severity_enum"), nullable=False
    )
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    limit_breached: Mapped[str | None] = mapped_column(String(100), nullable=True)
    current_value: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    limit_value: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)

    action_taken: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, name="metadata", nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"RiskEvent(type={self.event_type}, severity={self.severity}, at={self.triggered_at})"
        )
