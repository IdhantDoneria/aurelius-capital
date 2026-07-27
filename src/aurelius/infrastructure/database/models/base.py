"""SQLAlchemy base model with shared mixins.

All ORM models inherit from Base. Mixins are composed in.
Custom NUMERIC types ensure consistent financial precision across all models.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Numeric, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ── Financial precision types ─────────────────────────────────────────────────
# NUMERIC is exact. FLOAT is not. Never use FLOAT for prices, quantities, or PnL.

Price = Numeric(20, 8)          # Asset prices — supports crypto 8 decimal places
Quantity = Numeric(28, 4)       # Share/contract counts — large for ETF holdings
Notional = Numeric(28, 4)       # USD value of positions — billions-scale
Ratio = Numeric(20, 8)          # Ratios, multipliers, adjustment factors
FinancialRatio = Numeric(20, 4)  # P/E, P/B, margins — 4dp is sufficient
Percentage = Numeric(10, 6)     # -1.0 to 1.0 range, 6dp for basis point precision


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    type_annotation_map: dict[Any, Any] = {  # noqa: RUF012
        Decimal: Numeric(28, 8),
    }


# ── Mixins ────────────────────────────────────────────────────────────────────

class UUIDPrimaryKeyMixin:
    """UUID primary key. Use for business entities that need stable cross-system identity."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        comment="Stable UUID identifier, safe to expose in APIs",
    )


class TimestampMixin:
    """Automatic created_at / updated_at columns using database-side timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Row creation time (database clock)",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Last modification time (database clock)",
    )


class AuditMixin(TimestampMixin):
    """Adds created_by on top of timestamps. Used for user-facing records."""

    created_by: Mapped[str | None] = mapped_column(
        nullable=True,
        comment="Username or service that created this row",
    )
