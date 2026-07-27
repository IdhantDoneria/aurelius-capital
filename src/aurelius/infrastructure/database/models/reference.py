"""Reference / lookup tables: Exchange, DataSource, Symbol.

These are the dimension tables. Every fact table joins to symbols.
Symbol IDs are UUIDs for cross-system stability.

Key design rule: fact tables store symbol_id (UUID FK), NEVER the ticker string.
Tickers change (GOOGL → GOOG split, TWTR delisted). The UUID is stable.
"""

import enum as pyenum
import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    Date,
    Enum,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aurelius.infrastructure.database.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AssetClassEnum(pyenum.Enum):
    EQUITY = "equity"
    ETF = "etf"
    OPTION = "option"
    FUTURE = "future"
    FX = "fx"
    CRYPTO = "crypto"
    BOND = "bond"
    COMMODITY = "commodity"


class Exchange(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Financial exchange or trading venue.

    MIC code (ISO 10383) is the universal identifier.
    e.g. XNYS = NYSE, XNAS = NASDAQ, XCME = CME.
    """

    __tablename__ = "exchanges"

    mic_code: Mapped[str] = mapped_column(
        String(10),
        unique=True,
        nullable=False,
        comment="ISO 10383 Market Identifier Code",
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country_code: Mapped[str] = mapped_column(
        String(2),
        nullable=False,
        comment="ISO 3166-1 alpha-2 country code",
    )
    timezone: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="IANA timezone, e.g. America/New_York",
    )
    open_time: Mapped[str | None] = mapped_column(
        String(5),
        nullable=True,
        comment="Local market open time HH:MM",
    )
    close_time: Mapped[str | None] = mapped_column(
        String(5),
        nullable=True,
        comment="Local market close time HH:MM",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    symbols: Mapped[list["Symbol"]] = relationship("Symbol", back_populates="exchange")

    def __repr__(self) -> str:
        return f"Exchange(mic={self.mic_code!r})"


class DataSource(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Market data vendor or provider.

    Priority controls conflict resolution when the same bar exists from multiple sources.
    Lower priority number = higher preference (1 = best).
    """

    __tablename__ = "data_sources"

    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        comment="e.g. alpaca, bloomberg, refinitiv, polygon",
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    priority: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        comment="1=highest priority. Used when deduplicating overlapping data.",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    api_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"DataSource(name={self.name!r}, priority={self.priority})"


class Symbol(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tradeable instrument.

    Tickers are mutable (companies rename, merge, delist).
    The UUID id is the stable reference used in all fact tables.
    is_active + delisted_at tracks the full lifecycle.

    ISIN / CUSIP / FIGI are alternate identifiers for cross-source reconciliation.
    Bloomberg FIGI (Financial Instrument Global Identifier) is the most universal.
    """

    __tablename__ = "symbols"
    __table_args__ = (
        UniqueConstraint("ticker", "exchange_id", name="uq_symbols_ticker_exchange"),
        {"comment": "Tradeable instruments. The UUID is the stable cross-system identifier."},
    )

    ticker: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Exchange ticker symbol. May change — use id as stable reference.",
    )
    exchange_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        comment="FK to exchanges. Not declared as FK to avoid cross-partition issues.",
    )
    asset_class: Mapped[str] = mapped_column(
        Enum(AssetClassEnum, name="asset_class_enum"),
        nullable=False,
        server_default="equity",
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        server_default="USD",
        comment="ISO 4217 currency code",
    )
    company_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sector: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="GICS sector",
    )
    industry: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="GICS industry group",
    )

    # Universal identifiers for cross-source reconciliation
    isin: Mapped[str | None] = mapped_column(
        String(12),
        nullable=True,
        unique=True,
        comment="ISO 6166 International Securities Identification Number",
    )
    cusip: Mapped[str | None] = mapped_column(
        String(9),
        nullable=True,
        comment="CUSIP identifier (North America)",
    )
    figi: Mapped[str | None] = mapped_column(
        String(12),
        nullable=True,
        unique=True,
        comment="Bloomberg Financial Instrument Global Identifier",
    )

    # Lifecycle
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    listed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    delisted_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Relationships
    exchange: Mapped["Exchange"] = relationship("Exchange", back_populates="symbols")

    def __repr__(self) -> str:
        return f"Symbol(ticker={self.ticker!r}, exchange_id={self.exchange_id})"
