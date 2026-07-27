"""Initial schema: all tables, partitions, indexes.

Revision: 0001
Creates: ENUMs, reference tables, market data tables, fundamental tables,
         research tables, trading tables, partitions, BRIN indexes.

Design notes inline at each major section.
"""

# ruff: noqa: E501
from __future__ import annotations

import alembic.op as op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enable required PostgreSQL extensions ─────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")  # trigram text search

    # ── Create ENUMs ──────────────────────────────────────────────────────────
    # ENUMs are more efficient than VARCHAR: stored as 4-byte OID, enforced at DB level.
    op.execute("""
        CREATE TYPE asset_class_enum AS ENUM (
            'equity', 'etf', 'option', 'future', 'fx', 'crypto', 'bond', 'commodity'
        )
    """)
    op.execute("""
        CREATE TYPE statement_type_enum AS ENUM (
            'income_statement', 'balance_sheet', 'cash_flow'
        )
    """)
    op.execute("""
        CREATE TYPE period_type_enum AS ENUM (
            'annual', 'quarterly', 'ttm'
        )
    """)
    op.execute("""
        CREATE TYPE corporate_action_type_enum AS ENUM (
            'split', 'reverse_split', 'dividend_cash', 'dividend_stock',
            'spinoff', 'merger', 'acquisition', 'delisting',
            'name_change', 'ticker_change', 'rights_offering'
        )
    """)
    op.execute("""
        CREATE TYPE experiment_type_enum AS ENUM (
            'backtest', 'paper_trade', 'live', 'simulation'
        )
    """)
    op.execute("""
        CREATE TYPE experiment_status_enum AS ENUM (
            'pending', 'running', 'completed', 'failed', 'cancelled'
        )
    """)
    op.execute("""
        CREATE TYPE order_type_enum AS ENUM (
            'market', 'limit', 'stop', 'stop_limit', 'twap', 'vwap', 'pov', 'is'
        )
    """)
    op.execute("""
        CREATE TYPE order_side_enum AS ENUM (
            'buy', 'sell', 'sell_short', 'buy_to_cover'
        )
    """)
    op.execute("""
        CREATE TYPE order_status_enum AS ENUM (
            'pending', 'submitted', 'acknowledged', 'partial',
            'filled', 'cancelled', 'rejected', 'expired'
        )
    """)
    op.execute("""
        CREATE TYPE time_in_force_enum AS ENUM (
            'day', 'gtc', 'ioc', 'fok', 'gtd'
        )
    """)
    op.execute("""
        CREATE TYPE account_type_enum AS ENUM (
            'live', 'paper', 'margin', 'cash', 'ira'
        )
    """)
    op.execute("""
        CREATE TYPE risk_event_type_enum AS ENUM (
            'position_limit_breach', 'drawdown_limit', 'var_breach',
            'sector_concentration', 'margin_call',
            'kill_switch_triggered', 'circuit_breaker', 'loss_limit_daily'
        )
    """)
    op.execute("""
        CREATE TYPE risk_severity_enum AS ENUM (
            'info', 'warning', 'critical', 'fatal'
        )
    """)

    # ── REFERENCE TABLES ──────────────────────────────────────────────────────

    op.create_table(
        "exchanges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("mic_code", sa.String(10), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("timezone", sa.String(50), nullable=False),
        sa.Column("open_time", sa.String(5), nullable=True),
        sa.Column("close_time", sa.String(5), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "data_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("priority", sa.SmallInteger, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("api_base_url", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "symbols",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("exchange_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_class", sa.Enum("equity","etf","option","future","fx","crypto","bond","commodity",
                                          name="asset_class_enum"), nullable=False, server_default="equity"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("company_name", sa.String(500), nullable=True),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("isin", sa.String(12), nullable=True, unique=True),
        sa.Column("cusip", sa.String(9), nullable=True),
        sa.Column("figi", sa.String(12), nullable=True, unique=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("listed_at", sa.Date, nullable=True),
        sa.Column("delisted_at", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("ticker", "exchange_id", name="uq_symbols_ticker_exchange"),
        sa.ForeignKeyConstraint(["exchange_id"], ["exchanges.id"], name="fk_symbols_exchange"),
    )
    op.create_index("ix_symbols_ticker_exchange", "symbols", ["ticker", "exchange_id"])
    op.create_index("ix_symbols_asset_class_active", "symbols", ["asset_class", "is_active"])
    # Trigram index for company name search
    op.execute("CREATE INDEX ix_symbols_company_trgm ON symbols USING gin (company_name gin_trgm_ops)")

    # ── MARKET DATA TABLES (partitioned) ──────────────────────────────────────

    # OHLCV — partitioned monthly by timestamp
    # NUMERIC(20,8) for prices: exact, supports crypto precision
    op.execute("""
        CREATE TABLE market_data_ohlcv (
            id              BIGSERIAL,
            timestamp       TIMESTAMPTZ     NOT NULL,
            symbol_id       UUID            NOT NULL REFERENCES symbols(id),
            source_id       UUID            NOT NULL REFERENCES data_sources(id),
            frequency       VARCHAR(5)      NOT NULL,
            open            NUMERIC(20,8)   NOT NULL,
            high            NUMERIC(20,8)   NOT NULL,
            low             NUMERIC(20,8)   NOT NULL,
            close           NUMERIC(20,8)   NOT NULL,
            volume          NUMERIC(28,4)   NOT NULL,
            vwap            NUMERIC(20,8),
            trade_count     INTEGER,
            adjustment_factor NUMERIC(16,8) NOT NULL DEFAULT 1.0,
            quality_score   SMALLINT        NOT NULL DEFAULT 100,
            ingested_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
            PRIMARY KEY (id, timestamp),
            CONSTRAINT ck_ohlcv_high_gte_low    CHECK (high >= low),
            CONSTRAINT ck_ohlcv_high_gte_open   CHECK (high >= open),
            CONSTRAINT ck_ohlcv_high_gte_close  CHECK (high >= close),
            CONSTRAINT ck_ohlcv_low_lte_open    CHECK (low <= open),
            CONSTRAINT ck_ohlcv_low_lte_close   CHECK (low <= close),
            CONSTRAINT ck_ohlcv_prices_positive CHECK (open > 0 AND high > 0 AND low > 0 AND close > 0),
            CONSTRAINT ck_ohlcv_volume_nonneg   CHECK (volume >= 0),
            CONSTRAINT ck_ohlcv_quality_range   CHECK (quality_score BETWEEN 0 AND 100)
        ) PARTITION BY RANGE (timestamp)
    """)
    # B-tree composite index: primary query pattern (symbol + time + freq)
    op.execute("CREATE INDEX ix_ohlcv_symbol_ts_freq ON market_data_ohlcv (symbol_id, timestamp, frequency)")
    # BRIN: very cheap for monotonically-increasing timestamp, enables fast range scans
    op.execute("CREATE INDEX ix_ohlcv_ts_brin ON market_data_ohlcv USING brin (timestamp)")
    op.execute("CREATE INDEX ix_ohlcv_source_ingested ON market_data_ohlcv (source_id, ingested_at)")
    # Unique: one clean bar per symbol/timestamp/frequency/source
    op.execute("""
        CREATE UNIQUE INDEX uq_ohlcv_symbol_ts_freq_source
        ON market_data_ohlcv (symbol_id, timestamp, frequency, source_id)
    """)

    # Create monthly partitions for 2020-2026
    for year in range(2020, 2027):
        for month in range(1, 13):
            next_year = year if month < 12 else year + 1
            next_month = month + 1 if month < 12 else 1
            partition_name = f"market_data_ohlcv_y{year}m{month:02d}"
            op.execute(f"""
                CREATE TABLE {partition_name}
                PARTITION OF market_data_ohlcv
                FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01')
            """)

    # Ticks — partitioned daily (very high volume)
    op.execute("""
        CREATE TABLE market_data_ticks (
            id                  BIGSERIAL,
            timestamp           TIMESTAMPTZ     NOT NULL,
            symbol_id           UUID            NOT NULL REFERENCES symbols(id),
            source_id           UUID            NOT NULL REFERENCES data_sources(id),
            price               NUMERIC(20,8)   NOT NULL CHECK (price > 0),
            size                NUMERIC(20,4)   NOT NULL CHECK (size > 0),
            side                SMALLINT        NOT NULL DEFAULT 0 CHECK (side IN (0, 1, 2)),
            conditions          VARCHAR(5)[],
            exchange_sequence   BIGINT,
            ingested_at         TIMESTAMPTZ     NOT NULL DEFAULT now(),
            PRIMARY KEY (id, timestamp)
        ) PARTITION BY RANGE (timestamp)
    """)
    op.execute("CREATE INDEX ix_ticks_symbol_ts ON market_data_ticks (symbol_id, timestamp)")
    op.execute("CREATE INDEX ix_ticks_ts_brin ON market_data_ticks USING brin (timestamp)")

    # Create daily tick partitions for current year + next
    import datetime
    for year in [datetime.date.today().year, datetime.date.today().year + 1]:
        for month in range(1, 13):
            import calendar
            days_in_month = calendar.monthrange(year, month)[1]
            for day in range(1, days_in_month + 1):
                dt = datetime.date(year, month, day)
                next_dt = dt + datetime.timedelta(days=1)
                partition_name = f"market_data_ticks_{dt.strftime('%Y%m%d')}"
                op.execute(f"""
                    CREATE TABLE {partition_name}
                    PARTITION OF market_data_ticks
                    FOR VALUES FROM ('{dt}') TO ('{next_dt}')
                """)

    # Quotes — partitioned daily
    op.execute("""
        CREATE TABLE market_data_quotes (
            id              BIGSERIAL,
            timestamp       TIMESTAMPTZ     NOT NULL,
            symbol_id       UUID            NOT NULL REFERENCES symbols(id),
            source_id       UUID            NOT NULL REFERENCES data_sources(id),
            bid_price       NUMERIC(20,8)   NOT NULL CHECK (bid_price > 0),
            ask_price       NUMERIC(20,8)   NOT NULL CHECK (ask_price >= bid_price),
            bid_size        NUMERIC(20,4)   NOT NULL CHECK (bid_size >= 0),
            ask_size        NUMERIC(20,4)   NOT NULL CHECK (ask_size >= 0),
            bid_exchange    VARCHAR(10),
            ask_exchange    VARCHAR(10),
            nbbo_condition  VARCHAR(10),
            ingested_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
            PRIMARY KEY (id, timestamp)
        ) PARTITION BY RANGE (timestamp)
    """)
    op.execute("CREATE INDEX ix_quotes_symbol_ts ON market_data_quotes (symbol_id, timestamp)")
    op.execute("CREATE INDEX ix_quotes_ts_brin ON market_data_quotes USING brin (timestamp)")

    # Order book snapshots — partitioned daily
    op.execute("""
        CREATE TABLE order_book_snapshots (
            id              BIGSERIAL,
            timestamp       TIMESTAMPTZ     NOT NULL,
            symbol_id       UUID            NOT NULL REFERENCES symbols(id),
            source_id       UUID            NOT NULL REFERENCES data_sources(id),
            snapshot_depth  SMALLINT        NOT NULL,
            bids            JSONB           NOT NULL,
            asks            JSONB           NOT NULL,
            ingested_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),
            PRIMARY KEY (id, timestamp)
        ) PARTITION BY RANGE (timestamp)
    """)
    op.execute("CREATE INDEX ix_orderbook_symbol_ts ON order_book_snapshots (symbol_id, timestamp)")

    # Corporate actions — not partitioned (low volume, full-table scans acceptable)
    op.execute("""
        CREATE TABLE corporate_actions (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            symbol_id           UUID        NOT NULL REFERENCES symbols(id),
            action_type         corporate_action_type_enum NOT NULL,
            ex_date             TIMESTAMPTZ NOT NULL,
            record_date         TIMESTAMPTZ,
            pay_date            TIMESTAMPTZ,
            announcement_date   TIMESTAMPTZ,
            ratio               NUMERIC(20,8),
            cash_amount         NUMERIC(20,8),
            currency            VARCHAR(3)  NOT NULL DEFAULT 'USD',
            related_symbol_id   UUID        REFERENCES symbols(id),
            from_ticker         VARCHAR(20),
            to_ticker           VARCHAR(20),
            data_source         VARCHAR(50) NOT NULL,
            notes               TEXT,
            confirmed_at        TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_corp_action_symbol_exdate ON corporate_actions (symbol_id, ex_date)")
    op.execute("CREATE INDEX ix_corp_action_exdate ON corporate_actions (ex_date)")

    # ── FUNDAMENTAL DATA TABLES ───────────────────────────────────────────────

    op.execute("""
        CREATE TABLE financial_statements (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            symbol_id       UUID        NOT NULL REFERENCES symbols(id),
            source_id       UUID        NOT NULL REFERENCES data_sources(id),
            statement_type  statement_type_enum NOT NULL,
            period_type     period_type_enum    NOT NULL,
            fiscal_year     SMALLINT    NOT NULL,
            fiscal_quarter  SMALLINT    CHECK (fiscal_quarter BETWEEN 1 AND 4),
            period_end_date DATE        NOT NULL,
            filing_date     DATE        NOT NULL,
            currency        VARCHAR(3)  NOT NULL DEFAULT 'USD',
            revenue             NUMERIC(28,4),
            gross_profit        NUMERIC(28,4),
            operating_income    NUMERIC(28,4),
            net_income          NUMERIC(28,4),
            ebitda              NUMERIC(28,4),
            eps_basic           NUMERIC(20,4),
            eps_diluted         NUMERIC(20,4),
            shares_basic        NUMERIC(28,4),
            shares_diluted      NUMERIC(28,4),
            total_assets        NUMERIC(28,4),
            total_liabilities   NUMERIC(28,4),
            total_equity        NUMERIC(28,4),
            cash_and_equivalents NUMERIC(28,4),
            total_debt          NUMERIC(28,4),
            operating_cash_flow NUMERIC(28,4),
            capex               NUMERIC(28,4),
            free_cash_flow      NUMERIC(28,4),
            line_items      JSONB       NOT NULL DEFAULT '{}',
            is_restated     BOOLEAN     NOT NULL DEFAULT false,
            restated_at     DATE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_financial_statement UNIQUE (
                symbol_id, statement_type, period_type,
                fiscal_year, fiscal_quarter, is_restated
            )
        )
    """)
    op.execute("CREATE INDEX ix_fin_stmt_symbol_filing ON financial_statements (symbol_id, filing_date)")
    op.execute("CREATE INDEX ix_fin_stmt_symbol_period ON financial_statements (symbol_id, period_end_date)")
    op.execute("CREATE INDEX ix_fin_stmt_filing ON financial_statements (filing_date)")

    op.execute("""
        CREATE TABLE financial_ratios (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            symbol_id       UUID        NOT NULL REFERENCES symbols(id),
            source_id       UUID        NOT NULL REFERENCES data_sources(id),
            as_of_date      DATE        NOT NULL,
            filing_date     DATE        NOT NULL,
            period_type     period_type_enum NOT NULL,
            fiscal_year     SMALLINT    NOT NULL,
            fiscal_quarter  SMALLINT,
            pe_ratio            NUMERIC(20,4),
            forward_pe          NUMERIC(20,4),
            pb_ratio            NUMERIC(20,4),
            ps_ratio            NUMERIC(20,4),
            ev_to_ebitda        NUMERIC(20,4),
            ev_to_revenue       NUMERIC(20,4),
            ev_to_fcf           NUMERIC(20,4),
            price_to_fcf        NUMERIC(20,4),
            gross_margin        NUMERIC(20,4),
            operating_margin    NUMERIC(20,4),
            net_margin          NUMERIC(20,4),
            ebitda_margin       NUMERIC(20,4),
            fcf_margin          NUMERIC(20,4),
            roe                 NUMERIC(20,4),
            roa                 NUMERIC(20,4),
            roce                NUMERIC(20,4),
            roic                NUMERIC(20,4),
            debt_to_equity      NUMERIC(20,4),
            net_debt_to_ebitda  NUMERIC(20,4),
            interest_coverage   NUMERIC(20,4),
            current_ratio       NUMERIC(20,4),
            quick_ratio         NUMERIC(20,4),
            revenue_growth_yoy  NUMERIC(20,4),
            earnings_growth_yoy NUMERIC(20,4),
            fcf_growth_yoy      NUMERIC(20,4),
            market_cap          NUMERIC(28,4),
            enterprise_value    NUMERIC(28,4),
            shares_outstanding  NUMERIC(28,4),
            dividend_yield      NUMERIC(20,4),
            earnings_yield      NUMERIC(20,4),
            fcf_yield           NUMERIC(20,4),
            extended_metrics    JSONB   NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_fin_ratios_symbol_asof ON financial_ratios (symbol_id, as_of_date)")
    op.execute("CREATE INDEX ix_fin_ratios_symbol_filing ON financial_ratios (symbol_id, filing_date)")
    op.execute("CREATE INDEX ix_fin_ratios_asof ON financial_ratios (as_of_date)")

    op.execute("""
        CREATE TABLE earnings_events (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            symbol_id       UUID        NOT NULL REFERENCES symbols(id),
            source_id       UUID        NOT NULL REFERENCES data_sources(id),
            announced_at    TIMESTAMPTZ NOT NULL,
            fiscal_year     SMALLINT    NOT NULL,
            fiscal_quarter  SMALLINT    NOT NULL CHECK (fiscal_quarter BETWEEN 1 AND 4),
            period_end_date DATE        NOT NULL,
            eps_actual          NUMERIC(20,4),
            eps_estimate        NUMERIC(20,4),
            eps_surprise        NUMERIC(20,4),
            eps_surprise_pct    NUMERIC(10,4),
            revenue_actual      NUMERIC(28,4),
            revenue_estimate    NUMERIC(28,4),
            revenue_surprise_pct NUMERIC(10,4),
            guidance_eps_low    NUMERIC(20,4),
            guidance_eps_high   NUMERIC(20,4),
            guidance_revenue_low  NUMERIC(28,4),
            guidance_revenue_high NUMERIC(28,4),
            call_transcript_url TEXT,
            is_preliminary  BOOLEAN     NOT NULL DEFAULT false,
            metadata        JSONB       NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_earnings_symbol_period UNIQUE (symbol_id, fiscal_year, fiscal_quarter)
        )
    """)
    op.execute("CREATE INDEX ix_earnings_symbol_announced ON earnings_events (symbol_id, announced_at)")
    op.execute("CREATE INDEX ix_earnings_announced ON earnings_events (announced_at)")

    # ── RESEARCH DATA TABLES ──────────────────────────────────────────────────

    op.execute("""
        CREATE TABLE feature_definitions (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            name            VARCHAR(100) NOT NULL,
            version         SMALLINT    NOT NULL DEFAULT 1,
            display_name    VARCHAR(200),
            description     TEXT,
            category        VARCHAR(50) NOT NULL,
            computation_config JSONB   NOT NULL,
            dependencies    UUID[],
            lookback_days   INTEGER     NOT NULL DEFAULT 0,
            is_active       BOOLEAN     NOT NULL DEFAULT true,
            deprecated_at   TIMESTAMPTZ,
            created_by      VARCHAR(100) NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_feature_name_version UNIQUE (name, version)
        )
    """)
    op.execute("CREATE INDEX ix_feature_def_active ON feature_definitions (is_active)")
    op.execute("CREATE INDEX ix_feature_def_category ON feature_definitions (category)")

    op.execute("""
        CREATE TABLE feature_values (
            id              BIGSERIAL,
            timestamp       TIMESTAMPTZ NOT NULL,
            symbol_id       UUID        NOT NULL REFERENCES symbols(id),
            feature_id      UUID        NOT NULL REFERENCES feature_definitions(id),
            value           NUMERIC(28,8) NOT NULL,
            is_valid        BOOLEAN     NOT NULL DEFAULT true,
            computation_run_id UUID,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, timestamp)
        ) PARTITION BY RANGE (timestamp)
    """)
    op.execute("CREATE INDEX ix_feature_val_feature_ts ON feature_values (feature_id, timestamp)")
    op.execute("CREATE INDEX ix_feature_val_symbol_ts ON feature_values (symbol_id, timestamp)")
    op.execute("CREATE INDEX ix_feature_val_ts_brin ON feature_values USING brin (timestamp)")
    op.execute("""
        CREATE UNIQUE INDEX uq_feature_val_symbol_feature_ts
        ON feature_values (symbol_id, feature_id, timestamp)
    """)

    # Feature value partitions — monthly
    for year in range(2015, 2027):
        for month in range(1, 13):
            next_year = year if month < 12 else year + 1
            next_month = month + 1 if month < 12 else 1
            partition_name = f"feature_values_y{year}m{month:02d}"
            op.execute(f"""
                CREATE TABLE {partition_name}
                PARTITION OF feature_values
                FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01')
            """)

    op.execute("""
        CREATE TABLE experiment_runs (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            name            VARCHAR(200) NOT NULL,
            description     TEXT,
            run_type        experiment_type_enum NOT NULL,
            strategy_config JSONB       NOT NULL,
            universe_config JSONB       NOT NULL,
            backtest_config JSONB       NOT NULL,
            model_id        UUID,
            feature_ids     UUID[],
            status          experiment_status_enum NOT NULL DEFAULT 'pending',
            started_at      TIMESTAMPTZ,
            completed_at    TIMESTAMPTZ,
            error_message   TEXT,
            created_by      VARCHAR(100) NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_experiment_status ON experiment_runs (status)")

    op.execute("""
        CREATE TABLE experiment_metrics (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            experiment_id   UUID        NOT NULL REFERENCES experiment_runs(id),
            metric_name     VARCHAR(100) NOT NULL,
            metric_value    NUMERIC(20,8) NOT NULL,
            period_start    TIMESTAMPTZ NOT NULL,
            period_end      TIMESTAMPTZ NOT NULL,
            breakdown       JSONB,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_exp_metric UNIQUE (experiment_id, metric_name, period_start, period_end)
        )
    """)
    op.execute("CREATE INDEX ix_exp_metric_experiment ON experiment_metrics (experiment_id)")

    op.execute("""
        CREATE TABLE signal_predictions (
            id              BIGSERIAL,
            timestamp       TIMESTAMPTZ NOT NULL,
            symbol_id       UUID        NOT NULL REFERENCES symbols(id),
            experiment_id   UUID        NOT NULL REFERENCES experiment_runs(id),
            model_id        UUID,
            signal_value    NUMERIC(20,8) NOT NULL,
            signal_rank     NUMERIC(10,8),
            confidence      NUMERIC(10,8) CHECK (confidence BETWEEN 0 AND 1),
            horizon_days    SMALLINT    NOT NULL,
            metadata        JSONB       NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, timestamp)
        ) PARTITION BY RANGE (timestamp)
    """)
    op.execute("CREATE INDEX ix_signal_experiment_ts ON signal_predictions (experiment_id, timestamp)")
    op.execute("CREATE INDEX ix_signal_symbol_ts ON signal_predictions (symbol_id, timestamp)")

    # Signal prediction partitions — monthly
    for year in range(2020, 2027):
        for month in range(1, 13):
            next_year = year if month < 12 else year + 1
            next_month = month + 1 if month < 12 else 1
            partition_name = f"signal_predictions_y{year}m{month:02d}"
            op.execute(f"""
                CREATE TABLE {partition_name}
                PARTITION OF signal_predictions
                FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01')
            """)

    op.execute("""
        CREATE TABLE model_registry (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            name            VARCHAR(200) NOT NULL,
            version         INTEGER     NOT NULL,
            model_type      VARCHAR(50) NOT NULL,
            artifact_path   TEXT        NOT NULL,
            feature_ids     UUID[]      NOT NULL,
            training_start_date TIMESTAMPTZ NOT NULL,
            training_end_date   TIMESTAMPTZ NOT NULL,
            validation_metrics  JSONB   NOT NULL,
            hyperparameters     JSONB   NOT NULL,
            is_production   BOOLEAN     NOT NULL DEFAULT false,
            promoted_at     TIMESTAMPTZ,
            created_by      VARCHAR(100) NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_model_name_version UNIQUE (name, version)
        )
    """)
    op.execute("CREATE INDEX ix_model_production ON model_registry (is_production)")

    # ── TRADING DATA TABLES ───────────────────────────────────────────────────

    op.execute("""
        CREATE TABLE accounts (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            name            VARCHAR(200) NOT NULL,
            broker          VARCHAR(50) NOT NULL,
            account_number  VARCHAR(100) NOT NULL UNIQUE,
            account_type    account_type_enum NOT NULL,
            currency        VARCHAR(3)  NOT NULL DEFAULT 'USD',
            is_active       BOOLEAN     NOT NULL DEFAULT true,
            closed_at       TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE strategies (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            name            VARCHAR(200) NOT NULL,
            version         INTEGER     NOT NULL DEFAULT 1,
            description     TEXT,
            config          JSONB       NOT NULL,
            is_active       BOOLEAN     NOT NULL DEFAULT false,
            activated_at    TIMESTAMPTZ,
            deprecated_at   TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_strategy_name_version UNIQUE (name, version)
        )
    """)
    op.execute("CREATE INDEX ix_strategy_active ON strategies (is_active)")

    # Orders — partitioned monthly by submitted_at
    op.execute("""
        CREATE TABLE orders (
            id              UUID            NOT NULL DEFAULT gen_random_uuid(),
            submitted_at    TIMESTAMPTZ     NOT NULL,
            account_id      UUID            NOT NULL REFERENCES accounts(id),
            strategy_id     UUID            REFERENCES strategies(id),
            symbol_id       UUID            NOT NULL REFERENCES symbols(id),
            order_type      order_type_enum NOT NULL,
            side            order_side_enum NOT NULL,
            quantity        NUMERIC(28,4)   NOT NULL CHECK (quantity > 0),
            limit_price     NUMERIC(20,8),
            stop_price      NUMERIC(20,8),
            time_in_force   time_in_force_enum NOT NULL DEFAULT 'day',
            good_till_date  DATE,
            status          order_status_enum NOT NULL DEFAULT 'pending',
            filled_quantity NUMERIC(28,4)   NOT NULL DEFAULT 0 CHECK (filled_quantity >= 0),
            avg_fill_price  NUMERIC(20,8),
            broker_order_id VARCHAR(100),
            acknowledged_at TIMESTAMPTZ,
            first_fill_at   TIMESTAMPTZ,
            filled_at       TIMESTAMPTZ,
            cancelled_at    TIMESTAMPTZ,
            rejection_reason TEXT,
            parent_order_id UUID,
            metadata        JSONB           NOT NULL DEFAULT '{}',
            PRIMARY KEY (id, submitted_at)
        ) PARTITION BY RANGE (submitted_at)
    """)
    op.execute("CREATE INDEX ix_orders_account_status_ts ON orders (account_id, status, submitted_at)")
    op.execute("CREATE INDEX ix_orders_strategy_status_ts ON orders (strategy_id, status, submitted_at)")
    op.execute("CREATE INDEX ix_orders_symbol_ts ON orders (symbol_id, submitted_at)")
    op.execute("""
        CREATE INDEX ix_orders_active ON orders (status, submitted_at)
        WHERE status IN ('pending', 'submitted', 'acknowledged', 'partial')
    """)
    op.execute("""
        CREATE INDEX ix_orders_broker_id ON orders (broker_order_id)
        WHERE broker_order_id IS NOT NULL
    """)

    # Order partitions — monthly for 2020-2026
    for year in range(2020, 2027):
        for month in range(1, 13):
            next_year = year if month < 12 else year + 1
            next_month = month + 1 if month < 12 else 1
            partition_name = f"orders_y{year}m{month:02d}"
            op.execute(f"""
                CREATE TABLE {partition_name}
                PARTITION OF orders
                FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01')
            """)

    # Fills — partitioned monthly, immutable audit trail
    op.execute("""
        CREATE TABLE fills (
            id              UUID            NOT NULL DEFAULT gen_random_uuid(),
            timestamp       TIMESTAMPTZ     NOT NULL,
            order_id        UUID            NOT NULL,
            account_id      UUID            NOT NULL REFERENCES accounts(id),
            strategy_id     UUID            REFERENCES strategies(id),
            symbol_id       UUID            NOT NULL REFERENCES symbols(id),
            side            order_side_enum NOT NULL,
            price           NUMERIC(20,8)   NOT NULL CHECK (price > 0),
            quantity        NUMERIC(28,4)   NOT NULL CHECK (quantity > 0),
            notional_value  NUMERIC(28,4)   NOT NULL,
            commission      NUMERIC(28,4)   NOT NULL DEFAULT 0,
            commission_currency VARCHAR(3)  NOT NULL DEFAULT 'USD',
            exchange        VARCHAR(20),
            settlement_date DATE,
            broker_fill_id  VARCHAR(100)    UNIQUE,
            execution_latency_ms INTEGER,
            metadata        JSONB           NOT NULL DEFAULT '{}',
            PRIMARY KEY (id, timestamp)
        ) PARTITION BY RANGE (timestamp)
    """)
    op.execute("CREATE INDEX ix_fills_order_ts ON fills (order_id, timestamp)")
    op.execute("CREATE INDEX ix_fills_account_ts ON fills (account_id, timestamp)")
    op.execute("CREATE INDEX ix_fills_symbol_ts ON fills (symbol_id, timestamp)")
    op.execute("CREATE INDEX ix_fills_settlement ON fills (settlement_date)")
    op.execute("CREATE INDEX ix_fills_ts_brin ON fills USING brin (timestamp)")

    # Fill partitions — monthly for 2020-2026
    for year in range(2020, 2027):
        for month in range(1, 13):
            next_year = year if month < 12 else year + 1
            next_month = month + 1 if month < 12 else 1
            partition_name = f"fills_y{year}m{month:02d}"
            op.execute(f"""
                CREATE TABLE {partition_name}
                PARTITION OF fills
                FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01')
            """)

    # Positions — NOT partitioned (current state, not time-series)
    op.execute("""
        CREATE TABLE positions (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            account_id      UUID        NOT NULL REFERENCES accounts(id),
            strategy_id     UUID        REFERENCES strategies(id),
            symbol_id       UUID        NOT NULL REFERENCES symbols(id),
            quantity        NUMERIC(28,4) NOT NULL,
            avg_cost        NUMERIC(20,8) NOT NULL CHECK (avg_cost > 0),
            cost_basis      NUMERIC(28,4) NOT NULL,
            realized_pnl    NUMERIC(28,4) NOT NULL DEFAULT 0,
            unrealized_pnl  NUMERIC(28,4),
            last_price      NUMERIC(20,8),
            last_updated_at TIMESTAMPTZ,
            opened_at       TIMESTAMPTZ NOT NULL,
            closed_at       TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # Partial unique: only one open position per account/strategy/symbol
    op.execute("""
        CREATE UNIQUE INDEX uq_positions_open
        ON positions (account_id, strategy_id, symbol_id)
        WHERE closed_at IS NULL
    """)
    op.execute("CREATE INDEX ix_positions_account_open ON positions (account_id) WHERE closed_at IS NULL")
    op.execute("CREATE INDEX ix_positions_strategy_open ON positions (strategy_id) WHERE closed_at IS NULL")
    op.execute("CREATE INDEX ix_positions_symbol_open ON positions (symbol_id) WHERE closed_at IS NULL")

    # P&L snapshots — partitioned monthly
    op.execute("""
        CREATE TABLE pnl_snapshots (
            id                      BIGSERIAL,
            snapshot_at             TIMESTAMPTZ NOT NULL,
            account_id              UUID        NOT NULL REFERENCES accounts(id),
            strategy_id             UUID        REFERENCES strategies(id),
            total_equity            NUMERIC(28,4) NOT NULL,
            cash_balance            NUMERIC(28,4) NOT NULL,
            long_market_value       NUMERIC(28,4) NOT NULL,
            short_market_value      NUMERIC(28,4) NOT NULL,
            gross_exposure          NUMERIC(28,4) NOT NULL,
            net_exposure            NUMERIC(28,4) NOT NULL,
            leverage                NUMERIC(20,8) NOT NULL,
            realized_pnl_daily      NUMERIC(28,4) NOT NULL,
            realized_pnl_mtd        NUMERIC(28,4) NOT NULL,
            realized_pnl_ytd        NUMERIC(28,4) NOT NULL,
            unrealized_pnl          NUMERIC(28,4) NOT NULL,
            total_pnl_daily         NUMERIC(28,4) NOT NULL,
            total_commission_daily  NUMERIC(28,4) NOT NULL,
            sharpe_ratio_trailing   NUMERIC(20,8),
            max_drawdown_trailing   NUMERIC(20,8),
            var_95_daily            NUMERIC(28,4),
            position_count          INTEGER     NOT NULL,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, snapshot_at)
        ) PARTITION BY RANGE (snapshot_at)
    """)
    op.execute("CREATE INDEX ix_pnl_account_ts ON pnl_snapshots (account_id, snapshot_at)")
    op.execute("CREATE INDEX ix_pnl_strategy_ts ON pnl_snapshots (strategy_id, snapshot_at)")

    # PnL partitions — monthly
    for year in range(2020, 2027):
        for month in range(1, 13):
            next_year = year if month < 12 else year + 1
            next_month = month + 1 if month < 12 else 1
            partition_name = f"pnl_snapshots_y{year}m{month:02d}"
            op.execute(f"""
                CREATE TABLE {partition_name}
                PARTITION OF pnl_snapshots
                FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{next_year}-{next_month:02d}-01')
            """)

    # Risk events — not partitioned (relatively low volume)
    op.execute("""
        CREATE TABLE risk_events (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            account_id      UUID        REFERENCES accounts(id),
            strategy_id     UUID        REFERENCES strategies(id),
            event_type      risk_event_type_enum NOT NULL,
            severity        risk_severity_enum   NOT NULL,
            triggered_at    TIMESTAMPTZ NOT NULL,
            resolved_at     TIMESTAMPTZ,
            limit_breached  VARCHAR(100),
            current_value   NUMERIC(28,8),
            limit_value     NUMERIC(28,8),
            action_taken    TEXT,
            metadata        JSONB       NOT NULL DEFAULT '{}',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_risk_account_triggered ON risk_events (account_id, triggered_at)")
    op.execute("CREATE INDEX ix_risk_unresolved ON risk_events (triggered_at) WHERE resolved_at IS NULL")
    op.execute("CREATE INDEX ix_risk_severity ON risk_events (severity)")

    # ── SEED REFERENCE DATA ────────────────────────────────────────────────────

    op.execute("""
        INSERT INTO exchanges (id, mic_code, name, country_code, timezone, open_time, close_time)
        VALUES
            (gen_random_uuid(), 'XNYS', 'New York Stock Exchange', 'US', 'America/New_York', '09:30', '16:00'),
            (gen_random_uuid(), 'XNAS', 'NASDAQ', 'US', 'America/New_York', '09:30', '16:00'),
            (gen_random_uuid(), 'XCBF', 'CBOE', 'US', 'America/Chicago', '08:30', '15:15'),
            (gen_random_uuid(), 'XCME', 'CME Group', 'US', 'America/Chicago', '00:00', '23:59'),
            (gen_random_uuid(), 'XCHI', 'Chicago Stock Exchange', 'US', 'America/Chicago', '09:30', '16:00'),
            (gen_random_uuid(), 'XUNK', 'Unknown/OTC', 'US', 'America/New_York', NULL, NULL)
    """)

    op.execute("""
        INSERT INTO data_sources (id, name, display_name, priority)
        VALUES
            (gen_random_uuid(), 'alpaca', 'Alpaca Markets', 10),
            (gen_random_uuid(), 'polygon', 'Polygon.io', 5),
            (gen_random_uuid(), 'bloomberg', 'Bloomberg', 1),
            (gen_random_uuid(), 'refinitiv', 'Refinitiv (LSEG)', 2),
            (gen_random_uuid(), 'yahoo_finance', 'Yahoo Finance', 20)
    """)


def downgrade() -> None:
    """Drop all tables and types. DESTRUCTIVE — all data lost."""

    # Drop partitioned tables (drops all partitions too)
    for table in [
        "pnl_snapshots", "fills", "orders", "signal_predictions",
        "feature_values", "market_data_quotes", "order_book_snapshots",
        "market_data_ticks", "market_data_ohlcv",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    # Drop regular tables in reverse FK order
    for table in [
        "risk_events", "positions", "experiment_metrics", "experiment_runs",
        "model_registry", "earnings_events", "financial_ratios",
        "financial_statements", "corporate_actions", "feature_definitions",
        "strategies", "accounts", "symbols", "data_sources", "exchanges",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    # Drop ENUMs
    for enum in [
        "risk_severity_enum", "risk_event_type_enum", "account_type_enum",
        "time_in_force_enum", "order_status_enum", "order_side_enum",
        "order_type_enum", "experiment_status_enum", "experiment_type_enum",
        "corporate_action_type_enum", "period_type_enum", "statement_type_enum",
        "asset_class_enum",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum} CASCADE")
