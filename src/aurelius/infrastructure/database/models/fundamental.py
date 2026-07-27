"""Fundamental data ORM models: financial statements, ratios, earnings.

POINT-IN-TIME CORRECTNESS IS MANDATORY HERE.

Every table has both period_end_date (when the fiscal period ended) and
filing_date (when the data became publicly available via SEC filing).

Backtesting rule: JOIN fundamentals WHERE filing_date <= backtest_date.
NEVER join on period_end_date — that's look-ahead bias.

Example: Apple Q1 FY2024 ends Dec 31 2023. Filed Feb 2 2024.
A backtest running on Jan 15 2024 must NOT see this data.
Filing_date = Feb 2 2024 correctly excludes it.
"""

import enum as pyenum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from aurelius.infrastructure.database.models.base import (
    Base,
    FinancialRatio,
    Notional,
    TimestampMixin,
)


class StatementTypeEnum(pyenum.Enum):
    INCOME_STATEMENT = "income_statement"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"


class PeriodTypeEnum(pyenum.Enum):
    ANNUAL = "annual"
    QUARTERLY = "quarterly"
    TTM = "ttm"  # Trailing twelve months


class FinancialStatement(Base, TimestampMixin):
    """Financial statement data: income, balance sheet, cash flow.

    Line items stored in JSONB — they vary by company type, data vendor, and
    accounting standard (GAAP vs IFRS). Commonly queried metrics (revenue, EPS)
    are typed columns so you can index and aggregate them efficiently.
    The full line item detail lives in the JSONB.

    is_restated + restated_at: companies issue restated financials.
    The original and restated versions are both kept for audit.
    """

    __tablename__ = "financial_statements"
    __table_args__ = (
        UniqueConstraint(
            "symbol_id",
            "statement_type",
            "period_type",
            "fiscal_year",
            "fiscal_quarter",
            "is_restated",
            name="uq_financial_statement",
        ),
        Index("ix_fin_stmt_symbol_filing", "symbol_id", "filing_date"),
        Index("ix_fin_stmt_symbol_period", "symbol_id", "period_end_date"),
        Index("ix_fin_stmt_filing", "filing_date"),
        {
            "comment": (
                "QUERY WITH filing_date FOR POINT-IN-TIME CORRECTNESS. "
                "period_end_date is when the period ended, NOT when data was available."
            )
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    symbol_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    statement_type: Mapped[str] = mapped_column(
        Enum(StatementTypeEnum, name="statement_type_enum"), nullable=False
    )
    period_type: Mapped[str] = mapped_column(
        Enum(PeriodTypeEnum, name="period_type_enum"), nullable=False
    )
    fiscal_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    fiscal_quarter: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
        comment="NULL for annual. 1-4 for quarterly.",
    )

    # CRITICAL: use filing_date for point-in-time queries, NOT period_end_date
    period_end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment="End of fiscal period. NOT the date data became available.",
    )
    filing_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        comment=(
            "SEC filing date — when this data became publicly available. USE THIS for PIT queries."
        ),
    )

    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")

    # Typed summary metrics for efficient cross-sectional queries
    revenue: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    gross_profit: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    operating_income: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    net_income: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    ebitda: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    eps_basic: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    eps_diluted: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    shares_basic: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    shares_diluted: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)

    # Balance sheet summaries
    total_assets: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    total_liabilities: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    total_equity: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    cash_and_equivalents: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    total_debt: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)

    # Cash flow summaries
    operating_cash_flow: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    capex: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    free_cash_flow: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)

    # Full detail in JSONB — vendor-specific line items
    line_items: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="Complete line item detail from data vendor",
    )

    is_restated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    restated_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    def __repr__(self) -> str:
        return (
            f"FinancialStatement(symbol={self.symbol_id}, "
            f"type={self.statement_type}, FY{self.fiscal_year}Q{self.fiscal_quarter})"
        )


class FinancialRatios(Base, TimestampMixin):
    """Computed financial ratios — valuation, quality, growth, leverage.

    Most ratios require both fundamental data AND market prices (e.g., P/E needs both
    EPS from the filing and stock price at a point in time).

    as_of_date: the date the ratio was computed (uses market price from this date)
    filing_date: the most recent filing used in computation

    Both fields are required for point-in-time correct factor construction.
    """

    __tablename__ = "financial_ratios"
    __table_args__ = (
        Index("ix_fin_ratios_symbol_asof", "symbol_id", "as_of_date"),
        Index("ix_fin_ratios_symbol_filing", "symbol_id", "filing_date"),
        Index("ix_fin_ratios_asof", "as_of_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    symbol_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    filing_date: Mapped[date] = mapped_column(Date, nullable=False)
    period_type: Mapped[str] = mapped_column(
        Enum(PeriodTypeEnum, name="period_type_enum"), nullable=False
    )
    fiscal_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    fiscal_quarter: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Valuation
    pe_ratio: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    forward_pe: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    pb_ratio: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    ps_ratio: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    ev_to_ebitda: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    ev_to_revenue: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    ev_to_fcf: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    price_to_fcf: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)

    # Profitability
    gross_margin: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    operating_margin: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    net_margin: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    ebitda_margin: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    fcf_margin: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)

    # Returns
    roe: Mapped[Decimal | None] = mapped_column(
        FinancialRatio, nullable=True, comment="Return on Equity"
    )
    roa: Mapped[Decimal | None] = mapped_column(
        FinancialRatio, nullable=True, comment="Return on Assets"
    )
    roce: Mapped[Decimal | None] = mapped_column(
        FinancialRatio, nullable=True, comment="Return on Capital Employed"
    )
    roic: Mapped[Decimal | None] = mapped_column(
        FinancialRatio, nullable=True, comment="Return on Invested Capital"
    )

    # Leverage / solvency
    debt_to_equity: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    net_debt_to_ebitda: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    interest_coverage: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    current_ratio: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    quick_ratio: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)

    # Growth (YoY)
    revenue_growth_yoy: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    earnings_growth_yoy: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    fcf_growth_yoy: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)

    # Capital structure
    market_cap: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    enterprise_value: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    shares_outstanding: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)

    # Income / yield
    dividend_yield: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    earnings_yield: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)
    fcf_yield: Mapped[Decimal | None] = mapped_column(FinancialRatio, nullable=True)

    # Extended / vendor-specific
    extended_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class EarningsEvent(Base, TimestampMixin):
    """Quarterly earnings announcement with actual vs estimate comparison.

    announced_at: exact timestamp of the press release or call.
    This is critical for event studies — earnings drift strategies depend on
    knowing the precise announcement time (pre/post market matters).

    EPS surprise = eps_actual - eps_estimate (consensus at time of announcement).
    """

    __tablename__ = "earnings_events"
    __table_args__ = (
        UniqueConstraint(
            "symbol_id",
            "fiscal_year",
            "fiscal_quarter",
            name="uq_earnings_symbol_period",
        ),
        Index("ix_earnings_symbol_announced", "symbol_id", "announced_at"),
        Index("ix_earnings_announced", "announced_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    symbol_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    announced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Exact timestamp of announcement. Pre/post market matters for event studies.",
    )
    fiscal_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    fiscal_quarter: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    period_end_date: Mapped[date] = mapped_column(Date, nullable=False)

    # EPS — actual vs consensus estimate at time of announcement
    eps_actual: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    eps_estimate: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4),
        nullable=True,
        comment="Consensus analyst estimate at time of announcement",
    )
    eps_surprise: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4), nullable=True, comment="eps_actual - eps_estimate"
    )
    eps_surprise_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4),
        nullable=True,
        comment="Percentage surprise. Key signal for PEAD strategy.",
    )

    # Revenue
    revenue_actual: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    revenue_estimate: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    revenue_surprise_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    # Forward guidance (if provided)
    guidance_eps_low: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    guidance_eps_high: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    guidance_revenue_low: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)
    guidance_revenue_high: Mapped[Decimal | None] = mapped_column(Notional, nullable=True)

    call_transcript_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_preliminary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        comment="True if these are preliminary results, not final",
    )
    extra_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        name="metadata",  # DB column is still named 'metadata'
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    def __repr__(self) -> str:
        return (
            f"EarningsEvent(symbol={self.symbol_id}, "
            f"FY{self.fiscal_year}Q{self.fiscal_quarter}, "
            f"surprise={self.eps_surprise_pct}%)"
        )
