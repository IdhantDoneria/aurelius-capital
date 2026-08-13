"""Core market data entities and value objects.

These are the canonical data shapes used everywhere in the platform.
No I/O, no external dependencies — pure Python + Pydantic.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class AssetClass(StrEnum):
    EQUITY = "equity"
    ETF = "etf"
    OPTION = "option"
    FUTURE = "future"
    FX = "fx"
    CRYPTO = "crypto"


class Exchange(StrEnum):
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"
    CBOE = "CBOE"
    CME = "CME"
    UNKNOWN = "UNKNOWN"


class DataFrequency(StrEnum):
    TICK = "tick"
    SECOND = "1s"
    MINUTE = "1m"
    FIVE_MINUTE = "5m"
    FIFTEEN_MINUTE = "15m"
    HOUR = "1h"
    DAY = "1d"
    WEEK = "1w"
    MONTH = "1M"


class MarketSide(StrEnum):
    BUY = "buy"
    SELL = "sell"
    UNKNOWN = "unknown"


class Symbol(BaseModel):
    """Identifies a tradeable instrument."""

    ticker: str = Field(..., min_length=1, max_length=20, description="e.g. AAPL, BTC-USD")
    exchange: Exchange = Field(default=Exchange.UNKNOWN)
    asset_class: AssetClass = Field(default=AssetClass.EQUITY)

    @field_validator("ticker")
    @classmethod
    def ticker_uppercase(cls, v: str) -> str:
        return v.upper().strip()

    def __hash__(self) -> int:
        return hash((self.ticker, self.exchange))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Symbol):
            return NotImplemented
        return self.ticker == other.ticker and self.exchange == other.exchange

    def __str__(self) -> str:
        return f"{self.ticker}:{self.exchange}"


class OHLCV(BaseModel):
    """Open-High-Low-Close-Volume bar — the fundamental unit of market data."""

    symbol: Symbol
    timestamp: datetime
    frequency: DataFrequency
    open: Decimal = Field(..., gt=0, description="Opening price")
    high: Decimal = Field(..., gt=0, description="Highest price in period")
    low: Decimal = Field(..., gt=0, description="Lowest price in period")
    close: Decimal = Field(..., gt=0, description="Closing price")
    volume: Decimal = Field(..., ge=0, description="Volume traded")
    vwap: Decimal | None = Field(default=None, description="Volume-weighted average price")
    trade_count: int | None = Field(default=None, ge=0, description="Number of trades")

    @model_validator(mode="after")
    def validate_ohlc_relationships(self) -> "OHLCV":
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) must be >= low ({self.low})")
        if self.high < self.open:
            raise ValueError(f"high ({self.high}) must be >= open ({self.open})")
        if self.high < self.close:
            raise ValueError(f"high ({self.high}) must be >= close ({self.close})")
        if self.low > self.open:
            raise ValueError(f"low ({self.low}) must be <= open ({self.open})")
        if self.low > self.close:
            raise ValueError(f"low ({self.low}) must be <= close ({self.close})")
        return self

    @property
    def is_green(self) -> bool:
        return self.close >= self.open

    @property
    def body_size(self) -> Decimal:
        return abs(self.close - self.open)

    @property
    def range_size(self) -> Decimal:
        return self.high - self.low


class Tick(BaseModel):
    """Single trade tick — price and size at a point in time."""

    symbol: Symbol
    timestamp: datetime
    price: Decimal = Field(..., gt=0)
    size: Decimal = Field(..., gt=0)
    side: MarketSide = Field(default=MarketSide.UNKNOWN)
    exchange_sequence: int | None = Field(
        default=None, description="Exchange-assigned sequence number"
    )


class Quote(BaseModel):
    """Best bid/ask at a point in time."""

    symbol: Symbol
    timestamp: datetime
    bid_price: Decimal = Field(..., gt=0)
    ask_price: Decimal = Field(..., gt=0)
    bid_size: Decimal = Field(..., ge=0)
    ask_size: Decimal = Field(..., ge=0)

    @property
    def spread(self) -> Decimal:
        return self.ask_price - self.bid_price

    @property
    def mid_price(self) -> Decimal:
        return (self.bid_price + self.ask_price) / 2

    @model_validator(mode="after")
    def validate_spread(self) -> "Quote":
        if self.ask_price < self.bid_price:
            raise ValueError(f"ask ({self.ask_price}) must be >= bid ({self.bid_price})")
        return self


class TimeRange(BaseModel):
    """Inclusive time interval used for data queries."""

    start: datetime
    end: datetime
    frequency: DataFrequency = Field(default=DataFrequency.DAY)

    @model_validator(mode="after")
    def validate_range(self) -> "TimeRange":
        if self.end <= self.start:
            raise ValueError(f"end ({self.end}) must be after start ({self.start})")
        return self
