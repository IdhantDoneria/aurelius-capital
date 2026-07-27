"""Research data models: feature store, experiments, signals, model registry.

The feature store is the core of the research infrastructure.
Every alpha signal, ML model input, and strategy parameter flows through it.

Feature versioning: features evolve. feature_definitions has a version field.
When you change a feature's computation logic, create a new version, don't update.
The old version's values are preserved for reproducibility of historical experiments.

Point-in-time correctness: feature_values.timestamp is the as-of date.
A feature value at T=2024-01-15 was computed using only data available by that date.
"""

import enum as pyenum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from aurelius.infrastructure.database.models.base import Base, TimestampMixin


class ExperimentStatusEnum(pyenum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExperimentTypeEnum(pyenum.Enum):
    BACKTEST = "backtest"
    PAPER_TRADE = "paper_trade"
    LIVE = "live"
    SIMULATION = "simulation"


class FeatureDefinition(Base, TimestampMixin):
    """Defines a computable feature (alpha signal input).

    name + version: 'momentum_1m' v1 and v2 can coexist.
    computation_config: JSON schema for how to compute this feature.
    dependencies: other feature_ids this feature is derived from.
    lookback_days: minimum history required before this feature is valid.

    Example computation_config:
    {
      "lookback_days": 21,
      "inputs": ["close"],
      "formula": "(close - close_lag_21) / close_lag_21"
    }
    """

    __tablename__ = "feature_definitions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_feature_name_version"),
        Index("ix_feature_def_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="momentum, value, quality, volatility, macro, microstructure",
    )
    computation_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, comment="How to compute this feature"
    )
    dependencies: Mapped[list[str] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=True,
        comment="feature_ids this feature depends on",
    )
    lookback_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        comment="Minimum history in trading days required before feature is valid",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)

    def __repr__(self) -> str:
        return f"FeatureDefinition(name={self.name!r}, v{self.version})"


class FeatureValue(Base):
    """Computed feature values. Partitioned monthly by timestamp.

    This table is the hot path for strategy signal computation.
    A universe of 3000 symbols x 200 features x 252 trading days = 151M rows/year.
    Monthly partitions keep each partition to ~12M rows.

    is_valid=False marks outliers detected during quality checks.
    These rows are kept (not deleted) for audit — the pipeline that produced
    them can be rerun to produce valid replacements.

    computation_run_id links to the batch job that computed this row,
    enabling full lineage: which code version, which data version produced this value.
    """

    __tablename__ = "feature_values"
    __table_args__ = (
        UniqueConstraint(
            "symbol_id",
            "feature_id",
            "timestamp",
            name="uq_feature_value_symbol_feature_ts",
        ),
        Index("ix_feature_val_feature_ts", "feature_id", "timestamp"),
        Index("ix_feature_val_symbol_ts", "symbol_id", "timestamp"),
        {
            "postgresql_partition_by": "RANGE (timestamp)",
            "comment": "Partitioned monthly. 150M+ rows/year for typical universe.",
        },
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        nullable=False,
        comment=(
            "As-of date. Point-in-time correct — computed only from data available at this date."
        ),
    )

    symbol_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    feature_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(28, 8), nullable=False)

    is_valid: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
        comment="False if flagged as outlier. Row is kept for audit, not deleted.",
    )
    computation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="Links to the batch run that produced this value",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class ExperimentRun(Base, TimestampMixin):
    """A single research experiment: backtest, paper trade, or live run.

    Captures the full configuration at run time so results are reproducible.
    strategy_config, universe_config, backtest_config are all JSONB —
    they vary enormously by strategy type.
    """

    __tablename__ = "experiment_runs"
    __table_args__ = (
        Index("ix_experiment_status", "status"),
        Index("ix_experiment_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_type: Mapped[str] = mapped_column(
        Enum(ExperimentTypeEnum, name="experiment_type_enum"), nullable=False
    )

    # Full configuration snapshot — immutable after run starts
    strategy_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    universe_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="Which symbols, filters, rebalance rules",
    )
    backtest_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        comment="Date range, frequency, transaction cost model, slippage model",
    )

    model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    feature_ids: Mapped[list[str] | None] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=True)

    status: Mapped[str] = mapped_column(
        Enum(ExperimentStatusEnum, name="experiment_status_enum"),
        nullable=False,
        server_default="pending",
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)

    def __repr__(self) -> str:
        return f"ExperimentRun(name={self.name!r}, status={self.status})"


class ExperimentMetric(Base):
    """Performance metrics from a completed experiment.

    One row per metric per time period. This allows breakdown by year,
    by market regime, by sector, etc.

    metric_name examples: sharpe_ratio, max_drawdown, calmar_ratio,
    annual_return, information_ratio, hit_rate, avg_win_loss
    """

    __tablename__ = "experiment_metrics"
    __table_args__ = (
        Index("ix_exp_metric_experiment", "experiment_id"),
        UniqueConstraint(
            "experiment_id",
            "metric_name",
            "period_start",
            "period_end",
            name="uq_exp_metric",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    period_start: Mapped[date] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[date] = mapped_column(DateTime(timezone=True), nullable=False)
    breakdown: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="Metric broken down by year/sector/regime"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class SignalPrediction(Base):
    """Model-generated signal scores. Partitioned monthly.

    signal_value: raw model output (can be any range, model-dependent)
    signal_rank: cross-sectional rank within universe, normalized 0-1
    confidence: model's confidence in this prediction (where applicable)
    horizon_days: how many trading days forward this signal predicts
    """

    __tablename__ = "signal_predictions"
    __table_args__ = (
        Index("ix_signal_experiment_ts", "experiment_id", "timestamp"),
        Index("ix_signal_symbol_ts", "symbol_id", "timestamp"),
        {"postgresql_partition_by": "RANGE (timestamp)"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )

    symbol_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    experiment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    signal_value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    signal_rank: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 8),
        nullable=True,
        comment="Cross-sectional rank 0-1. 1.0 = top signal in universe.",
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    horizon_days: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        comment="Prediction horizon in trading days",
    )
    extra_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        name="metadata",
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class ModelRegistry(Base, TimestampMixin):
    """Trained ML model metadata and artifact pointer.

    artifact_path points to the serialized model (S3/local).
    is_production: only one model per name should be production at a time
    (not enforced in DB — enforced at application layer).
    """

    __tablename__ = "model_registry"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_model_name_version"),
        Index("ix_model_production", "is_production"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="lgbm, xgboost, neural_net, linear, ensemble",
    )
    artifact_path: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Path to serialized model artifact"
    )
    feature_ids: Mapped[list[str]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    training_start_date: Mapped[date] = mapped_column(DateTime(timezone=True), nullable=False)
    training_end_date: Mapped[date] = mapped_column(DateTime(timezone=True), nullable=False)
    validation_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    hyperparameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_production: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)

    def __repr__(self) -> str:
        return f"ModelRegistry(name={self.name!r}, v{self.version}, prod={self.is_production})"
