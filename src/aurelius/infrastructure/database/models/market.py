"""Market data ORM models.

All time-series tables (OHLCV, Tick, Quote, OrderBook) are partitioned
by timestamp in the database. SQLAlchemy maps to the parent table; PostgreSQL
routes inserts to the correct partition automatically.

PARTITION DESIGN:
- ohlcv: monthly partitions (daily bars ~125K rows/month for 5000 symbols)
- ticks: daily partitions (1M+ ticks/day for liquid names)
- quotes: daily partitions
- order_book_snapshots: daily partitions

ORM maps to parent tables. Partition creation happens in migrations.
"""

import enum as pyenum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from aurelius.infrastructure.database.models.base import (
    Base,
)


class CorporateActionTypeEnum(pyenum.Enum):
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    DIVIDEND_CASH = "dividend_cash"
    DIVIDEND_STOCK = "dividend_stock"
    SPINOFF = "spinoff"
    MERGER = "merger"
    ACQUISITION = "acquisition"
    DELISTING = "delisting"
    NAME_CHANGE = "name_change"
    TICKER_CHANGE = "ticker_change"
    RIGHTS_OFFERING = "rights_offering"


class MarketDataOHLCV(Base):
    """OHLCV price bars. The fundamental unit of market data.

    PARTITION BY RANGE (timestamp) — monthly partitions.

    Stores raw (unadjusted) prices with adjustment_factor.
    Adjusted price = raw_price x adjustment_factor.
    When corporate action occurs: update adjustment_factor for all prior rows.
    This is cheaper than recomputing adjusted prices and avoids data duplication.

    quality_score: 0-100.
    - 100: pristine data from primary source, all fields present
    - 80+: minor gaps (missing vwap/trade_count)
    - 60+: interpolated or estimated values
    - <60: suspect — use with caution
    """

    __tablename__ = "market_data_ohlcv"

    # BIGSERIAL for time-series: sequential, cache-friendly, 8-byte vs 16-byte UUID.
    # Composite PK with timestamp required for partitioned tables.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,  # partition key must be in PK
        nullable=False,
        comment="Bar open time in UTC",
    )

    symbol_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    frequency: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
        comment="Bar frequency: 1d, 1h, 5m, 1m, 1s",
    )

    # OHLCV — all NUMERIC(20,8), never FLOAT
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(28, 4), nullable=False)

    # Optional enrichment fields
    vwap: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Adjustment
    adjustment_factor: Mapped[Decimal] = mapped_column(
        Numeric(16, 8),
        nullable=False,
        server_default=text("1.0"),
        comment="Multiply raw prices by this to get adjusted prices. Default 1.0.",
    )

    # Data quality
    quality_score: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        server_default=text("100"),
        comment="0-100. 100=pristine. <60=suspect.",
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When this row was written to the database",
    )

    __table_args__ = (
        Index("ix_ohlcv_symbol_ts_freq", "symbol_id", "timestamp", "frequency"),
        # BRIN for range scans — defined in migration DDL, not here
        # (SQLAlchemy Index doesn't support BRIN postgresql_using)
        {
            "postgresql_partition_by": "RANGE (timestamp)",
            "comment": "Partitioned monthly. Insert goes to correct partition automatically.",
        },
    )

    @property
    def adjusted_close(self) -> Decimal:
        return self.close * self.adjustment_factor

    @property
    def is_suspect(self) -> bool:
        return self.quality_score < 60

    def __repr__(self) -> str:
        return f"OHLCV(symbol={self.symbol_id}, ts={self.timestamp}, close={self.close})"


class MarketDataTick(Base):
    """Individual trade ticks. Very high volume — daily partitions.

    side: 0=unknown, 1=buy-initiated, 2=sell-initiated.
    Exchange-assigned sequence numbers allow deduplication.
    conditions: array of exchange trade condition codes (e.g. ['@', 'I', 'T']).
    """

    __tablename__ = "market_data_ticks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )

    symbol_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    size: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    side: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        server_default=text("0"),
        comment="0=unknown, 1=buy, 2=sell",
    )
    conditions: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(5)),
        nullable=True,
        comment="Exchange trade condition codes",
    )
    exchange_sequence: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="Exchange-assigned sequence. Use for deduplication.",
    )
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_ticks_symbol_ts", "symbol_id", "timestamp"),
        {
            "postgresql_partition_by": "RANGE (timestamp)",
            "comment": "Partitioned daily. Detach+drop for data retention management.",
        },
    )


class MarketDataQuote(Base):
    """Best bid/ask (NBBO) quotes. Daily partitions.

    For options/futures, bid_exchange/ask_exchange track which venue has the best.
    nbbo_condition flags non-standard NBBO states (e.g. 'R' = regular, 'X' = crossing).
    """

    __tablename__ = "market_data_quotes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )

    symbol_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    bid_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    ask_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    bid_size: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    ask_size: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    bid_exchange: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ask_exchange: Mapped[str | None] = mapped_column(String(10), nullable=True)
    nbbo_condition: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_quotes_symbol_ts", "symbol_id", "timestamp"),
        {"postgresql_partition_by": "RANGE (timestamp)"},
    )

    @property
    def spread(self) -> Decimal:
        return self.ask_price - self.bid_price

    @property
    def mid(self) -> Decimal:
        return (self.bid_price + self.ask_price) / 2


class OrderBookSnapshot(Base):
    """Order book depth snapshot. JSONB for bids/asks — depth varies per symbol/venue.

    bids/asks schema: [{"price": "150.25", "size": "100"}, ...]
    Sorted: bids descending by price, asks ascending by price.
    JSONB lets you query with @> operators and GIN indexes if needed.
    """

    __tablename__ = "order_book_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )

    symbol_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    snapshot_depth: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        comment="Number of price levels captured on each side",
    )
    bids: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment='[{"price": "...", "size": "..."}, ...] descending by price',
    )
    asks: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment='[{"price": "...", "size": "..."}, ...] ascending by price',
    )
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_orderbook_symbol_ts", "symbol_id", "timestamp"),
        {"postgresql_partition_by": "RANGE (timestamp)"},
    )


class CorporateAction(Base):
    """Corporate actions — splits, dividends, mergers, spinoffs.

    ex_date is the key field: the date on which you must hold shares to be entitled.
    When backtesting: apply adjustment_factor to all price data with timestamp < ex_date.

    For splits: ratio = new_shares / old_shares (2.0 for 2:1 split).
    For dividends: cash_amount = dividend per share in currency.
    For mergers: acquirer_symbol_id links to the acquiring company.
    """

    __tablename__ = "corporate_actions"
    __table_args__ = (
        Index("ix_corp_action_symbol_exdate", "symbol_id", "ex_date"),
        Index("ix_corp_action_exdate", "ex_date"),
        {
            "comment": (
                "Source of truth for price adjustments. "
                "Any OHLCV query for backtesting must join this table to apply adjustments."
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    symbol_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    action_type: Mapped[str] = mapped_column(
        Enum(CorporateActionTypeEnum, name="corporate_action_type_enum"),
        nullable=False,
    )

    # Key dates
    ex_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Ex-dividend/ex-rights date. Adjustment applies to data before this date.",
    )
    record_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pay_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    announcement_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Action specifics
    ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
        comment="Split ratio (new/old). 2.0 = 2:1 split. 0.5 = 1:2 reverse split.",
    )
    cash_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 8),
        nullable=True,
        comment="Cash dividend per share",
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")

    # For corporate restructuring
    related_symbol_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Acquirer/spinoff parent symbol",
    )
    from_ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Audit
    data_source: Mapped[str] = mapped_column(String(50), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"CorporateAction(symbol={self.symbol_id}, type={self.action_type}, ex={self.ex_date})"
        )
