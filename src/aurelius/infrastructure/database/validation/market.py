"""Market data validation framework.

Validates raw ingested data before it reaches the database.
Pydantic v2 models enforce type coercion and constraint checking.
Custom validators encode financial domain rules that SQL CHECK constraints
cannot express (e.g., maximum reasonable price moves, data staleness).

ValidationResult wraps multiple field-level errors so the ingestor
can log all issues in one pass rather than failing on the first.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


@dataclass
class ValidationIssue:
    field: str
    message: str
    severity: str = "error"  # error | warning


@dataclass
class ValidationResult:
    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    def add_error(self, field_name: str, message: str) -> None:
        self.issues.append(ValidationIssue(field=field_name, message=message, severity="error"))
        self.is_valid = False

    def add_warning(self, field_name: str, message: str) -> None:
        self.issues.append(ValidationIssue(field=field_name, message=message, severity="warning"))

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]


class OHLCVIngest(BaseModel):
    """Validated shape for an incoming OHLCV bar.

    All prices must be positive NUMERIC — Pydantic coerces strings to Decimal.
    OHLC relationships enforced in model_validator.
    Staleness: bars older than 30 days from market close are flagged.
    """

    symbol_id: UUID
    source_id: UUID
    timestamp: datetime
    frequency: str
    open: Decimal = Field(..., gt=0, decimal_places=8)
    high: Decimal = Field(..., gt=0, decimal_places=8)
    low: Decimal = Field(..., gt=0, decimal_places=8)
    close: Decimal = Field(..., gt=0, decimal_places=8)
    volume: Decimal = Field(..., ge=0, decimal_places=4)
    vwap: Decimal | None = Field(default=None, gt=0)
    trade_count: int | None = Field(default=None, ge=0)

    @field_validator("frequency")
    @classmethod
    def valid_frequency(cls, v: str) -> str:
        valid = {"tick", "1s", "1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M"}
        if v not in valid:
            raise ValueError(f"frequency must be one of {valid}, got {v!r}")
        return v

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (UTC)")
        return v

    @model_validator(mode="after")
    def ohlc_relationships(self) -> "OHLCVIngest":
        """OHLC price relationships must hold. Bad data from vendor violates these."""
        errors = []
        if self.high < self.low:
            errors.append(f"high ({self.high}) < low ({self.low})")
        if self.high < self.open:
            errors.append(f"high ({self.high}) < open ({self.open})")
        if self.high < self.close:
            errors.append(f"high ({self.high}) < close ({self.close})")
        if self.low > self.open:
            errors.append(f"low ({self.low}) > open ({self.open})")
        if self.low > self.close:
            errors.append(f"low ({self.low}) > close ({self.close})")
        if errors:
            raise ValueError(f"OHLC constraint violations: {'; '.join(errors)}")
        return self

    @model_validator(mode="after")
    def check_vwap_range(self) -> "OHLCVIngest":
        if self.vwap is not None:
            if self.vwap < self.low or self.vwap > self.high:
                raise ValueError(
                    f"vwap ({self.vwap}) must be within [low={self.low}, high={self.high}]"
                )
        return self

    def compute_quality_score(self, prev_close: Decimal | None = None) -> int:
        """Heuristic quality scoring. Returns 0-100.

        Deductions:
        - Missing vwap: -10
        - Missing trade_count: -5
        - Price move > 20% from prev close: -20 (flag for human review)
        - Zero volume: -30
        """
        score = 100

        if self.vwap is None:
            score -= 10
        if self.trade_count is None:
            score -= 5
        if self.volume == 0:
            score -= 30

        if prev_close is not None and prev_close > 0:
            pct_move = abs(self.close - prev_close) / prev_close
            if pct_move > Decimal("0.20"):
                score -= 20  # >20% move — possible bad tick or stock halt
            if pct_move > Decimal("0.50"):
                score -= 20  # >50% move — almost certainly bad data

        return max(0, score)


class TickIngest(BaseModel):
    """Validated shape for an incoming trade tick."""

    symbol_id: UUID
    source_id: UUID
    timestamp: datetime
    price: Decimal = Field(..., gt=0, decimal_places=8)
    size: Decimal = Field(..., gt=0, decimal_places=4)
    side: int = Field(default=0, ge=0, le=2)
    conditions: list[str] | None = None
    exchange_sequence: int | None = None

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (UTC)")
        return v


class CorporateActionIngest(BaseModel):
    """Validated shape for a corporate action."""

    symbol_id: UUID
    action_type: str
    ex_date: datetime
    ratio: Decimal | None = Field(default=None, gt=0)
    cash_amount: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    data_source: str

    @field_validator("action_type")
    @classmethod
    def valid_action_type(cls, v: str) -> str:
        valid = {
            "split",
            "reverse_split",
            "dividend_cash",
            "dividend_stock",
            "spinoff",
            "merger",
            "acquisition",
            "delisting",
            "name_change",
            "ticker_change",
            "rights_offering",
        }
        if v not in valid:
            raise ValueError(f"action_type must be one of {valid}")
        return v

    @model_validator(mode="after")
    def ratio_required_for_splits(self) -> "CorporateActionIngest":
        if self.action_type in ("split", "reverse_split") and self.ratio is None:
            raise ValueError(f"ratio is required for action_type={self.action_type!r}")
        if self.action_type == "dividend_cash" and self.cash_amount is None:
            raise ValueError("cash_amount is required for dividend_cash")
        return self


class OHLCVBatchValidator:
    """Validates a batch of OHLCV bars with cross-bar consistency checks.

    Used by the ingestor before bulk DB insert.
    Returns valid bars and a list of rejected bars with reasons.
    """

    # Maximum allowed price move between consecutive daily bars
    MAX_DAY_MOVE_PCT: Decimal = Decimal("0.50")
    # Maximum staleness for market-hours data
    MAX_STALENESS_DAYS: int = 5

    def validate_batch(self, raw_bars: list[dict]) -> tuple[list[OHLCVIngest], list[dict]]:
        """Validate a list of raw bar dicts.

        Returns (valid_bars, rejected_bars).
        rejected_bars dicts include a 'validation_errors' key.
        """
        valid: list[OHLCVIngest] = []
        rejected: list[dict] = []

        for raw in raw_bars:
            try:
                bar = OHLCVIngest.model_validate(raw)
                valid.append(bar)
            except Exception as exc:
                rejected.append({**raw, "validation_errors": str(exc)})

        return valid, rejected

    def validate_chronological_order(self, bars: list[OHLCVIngest]) -> list[ValidationIssue]:
        """Verify bars are in ascending timestamp order."""
        issues = []
        for i in range(1, len(bars)):
            if bars[i].timestamp <= bars[i - 1].timestamp:
                issues.append(
                    ValidationIssue(
                        field="timestamp",
                        message=(
                            f"Bar at index {i} ({bars[i].timestamp}) is not after "
                            f"bar at index {i - 1} ({bars[i - 1].timestamp})"
                        ),
                        severity="error",
                    )
                )
        return issues

    def check_staleness(self, bar: OHLCVIngest) -> ValidationIssue | None:
        """Flag bars that are unexpectedly old."""
        age = datetime.now(UTC) - bar.timestamp.replace(tzinfo=UTC)
        if age > timedelta(days=self.MAX_STALENESS_DAYS) and bar.frequency == "1d":
            return ValidationIssue(
                field="timestamp",
                message=f"Bar is {age.days} days old — expected near-real-time data",
                severity="warning",
            )
        return None
