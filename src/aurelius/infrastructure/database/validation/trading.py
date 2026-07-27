"""Trading data validation: orders, fills, positions.

Order validation enforces the state machine and business rules.
Fill validation checks against the originating order before committing.
These run BEFORE any DB write — fail early at the edge.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class OrderCreateRequest(BaseModel):
    """Validated input for creating a new order.

    Limit price required for limit/stop_limit orders.
    Stop price required for stop/stop_limit orders.
    IOC/FOK orders cannot be GTD or GTC.
    """

    account_id: UUID
    strategy_id: UUID | None = None
    symbol_id: UUID
    order_type: str
    side: str
    quantity: Decimal = Field(..., gt=0, decimal_places=4)
    limit_price: Decimal | None = Field(default=None, gt=0)
    stop_price: Decimal | None = Field(default=None, gt=0)
    time_in_force: str = "day"
    good_till_date: datetime | None = None

    @field_validator("order_type")
    @classmethod
    def valid_order_type(cls, v: str) -> str:
        valid = {"market", "limit", "stop", "stop_limit", "twap", "vwap", "pov", "is"}
        if v not in valid:
            raise ValueError(f"order_type must be one of {valid}")
        return v

    @field_validator("side")
    @classmethod
    def valid_side(cls, v: str) -> str:
        valid = {"buy", "sell", "sell_short", "buy_to_cover"}
        if v not in valid:
            raise ValueError(f"side must be one of {valid}")
        return v

    @field_validator("time_in_force")
    @classmethod
    def valid_tif(cls, v: str) -> str:
        valid = {"day", "gtc", "ioc", "fok", "gtd"}
        if v not in valid:
            raise ValueError(f"time_in_force must be one of {valid}")
        return v

    @model_validator(mode="after")
    def price_requirements(self) -> "OrderCreateRequest":
        errors = []
        if self.order_type in ("limit", "stop_limit") and self.limit_price is None:
            errors.append("limit_price required for limit/stop_limit orders")
        if self.order_type in ("stop", "stop_limit") and self.stop_price is None:
            errors.append("stop_price required for stop/stop_limit orders")
        if self.time_in_force in ("ioc", "fok") and self.time_in_force == "gtc":
            errors.append("IOC/FOK cannot be GTC")
        if self.time_in_force == "gtd" and self.good_till_date is None:
            errors.append("good_till_date required for GTD orders")
        if errors:
            raise ValueError(f"Order validation failed: {'; '.join(errors)}")
        return self


class FillIngest(BaseModel):
    """Validated shape for an incoming fill event.

    notional_value must be consistent with price x quantity within tolerance.
    Broker fill ID must be present for live trading (idempotency on re-delivery).
    """

    order_id: UUID
    account_id: UUID
    strategy_id: UUID | None = None
    symbol_id: UUID
    timestamp: datetime
    side: str
    price: Decimal = Field(..., gt=0, decimal_places=8)
    quantity: Decimal = Field(..., gt=0, decimal_places=4)
    notional_value: Decimal = Field(..., gt=0, decimal_places=4)
    commission: Decimal = Field(default=Decimal(0), ge=0)
    commission_currency: str = Field(default="USD", min_length=3, max_length=3)
    exchange: str | None = None
    settlement_date: datetime | None = None
    broker_fill_id: str | None = None
    execution_latency_ms: int | None = Field(default=None, ge=0)

    @field_validator("timestamp")
    @classmethod
    def must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (UTC)")
        return v

    @model_validator(mode="after")
    def notional_consistency(self) -> "FillIngest":
        """Notional must be within 0.01% of price x quantity."""
        expected = self.price * self.quantity
        tolerance = expected * Decimal("0.0001")
        if abs(self.notional_value - expected) > tolerance:
            raise ValueError(
                f"notional_value ({self.notional_value}) inconsistent with "
                f"price x quantity ({expected}). Tolerance: {tolerance}"
            )
        return self


class PositionCloseRequest(BaseModel):
    """Validated input for closing a position."""

    account_id: UUID
    symbol_id: UUID
    strategy_id: UUID | None = None
    close_quantity: Decimal | None = Field(
        default=None,
        gt=0,
        description="Quantity to close. None = close entire position.",
    )
    order_type: str = "market"
    limit_price: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def limit_price_for_limit_order(self) -> "PositionCloseRequest":
        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit_price required when order_type='limit'")
        return self
