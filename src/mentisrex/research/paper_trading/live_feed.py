"""Real market-data → M23 paper-trading bridge (PAPER_LIVE_FEED mode).

Wires the existing M21 Yahoo adapter → M20 SourceMessages → M19 normalizer
→ M18 MarketDataSnapshot → M23 PaperTradingLoop.process_snapshot().

Architecture (per forward-integration spec section 4):

    M21 YahooFinanceSourceAdapter.convert(records, as_of)
          ↓  list[SourceMessage]
    M20  extract OBSERVATION payloads
          ↓  list[dict]
    M19  Normalizer + MarketDataQualityEngine
          ↓  accepted CanonicalObservations
    M18  MarketDataSnapshotBuilder → MarketDataSnapshot
          ↓
    M23  PaperTradingLoop.process_snapshot(snapshot)

No provider-specific objects escape the adapter. No data is fabricated.
No real capital is deployed.

Data source limitation:
    Yahoo Finance via yfinance is a free/public provider. It is NOT equivalent
    to Bloomberg, Refinitiv, or institutional exchange-grade data. Observations
    may be delayed, adjusted retroactively, or occasionally erroneous. This feed
    is suitable for research paper-trading only.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from mentisrex.research.market_data.identifiers import IdentifierMap
from mentisrex.research.market_data.normalization import Normalizer
from mentisrex.research.market_data.pit import (
    BuildResult,
    MarketDataSnapshotBuilder,
    PITPolicy,
    SnapshotBuildError,
)
from mentisrex.research.market_data.providers.yahoo.adapter import YahooFinanceSourceAdapter
from mentisrex.research.market_data.quality import MarketDataQualityEngine, QualityConfig
from mentisrex.research.market_data_ops.messages import MessageType


@dataclass(frozen=True)
class LiveFeedConfig:
    """Configuration for the real-data feed.

    No credentials are needed for Yahoo Finance (yfinance is credential-free).
    """

    universe: tuple  # tickers / security_ids matching the strategy universe
    fetch_window_days: int = 5  # fetch last N calendar days of data (recent observations only)
    max_staleness_days: int = 5  # reject observations older than N days vs as_of
    provider_name: str = "yahoo_finance"
    timezone: str = "America/New_York"
    id_map: IdentifierMap | None = None
    # PITPolicy: fail_closed=False so a bad observation skips that security rather than
    # crashing the entire cycle.
    pit_fail_closed: bool = False


@dataclass
class FeedMetrics:
    """Operational metrics for section 13 observability requirements."""

    provider: str = "yahoo_finance"
    # DATA FEED
    requests: int = 0
    successful_responses: int = 0
    failed_responses: int = 0
    observations_received: int = 0
    observations_rejected: int = 0
    snapshots_created: int = 0
    snapshots_rejected: int = 0
    stale_observations: int = 0
    duplicate_observations: int = 0
    pit_violations: int = 0
    missing_securities: list = field(default_factory=list)
    # PIPELINE latencies (seconds)
    fetch_latencies: list = field(default_factory=list)
    normalization_latencies: list = field(default_factory=list)
    build_latencies: list = field(default_factory=list)
    # TRADING (filled in by caller from loop results)
    evaluations: int = 0
    signals_generated: int = 0
    orders_generated: int = 0
    fills: int = 0
    risk_rejections: int = 0
    # ACCOUNTING
    last_nav: float = 0.0
    last_cash: float = 0.0
    reconciliation_ok: bool = True

    def report(self) -> dict:
        return {
            "provider": self.provider,
            "requests": self.requests,
            "successful_responses": self.successful_responses,
            "failed_responses": self.failed_responses,
            "observations_received": self.observations_received,
            "observations_rejected": self.observations_rejected,
            "snapshots_created": self.snapshots_created,
            "snapshots_rejected": self.snapshots_rejected,
            "stale_observations": self.stale_observations,
            "pit_violations": self.pit_violations,
            "missing_securities": self.missing_securities,
            "avg_fetch_latency_s": (
                sum(self.fetch_latencies) / len(self.fetch_latencies)
                if self.fetch_latencies
                else 0.0
            ),
            "avg_normalization_latency_s": (
                sum(self.normalization_latencies) / len(self.normalization_latencies)
                if self.normalization_latencies
                else 0.0
            ),
            "avg_build_latency_s": (
                sum(self.build_latencies) / len(self.build_latencies)
                if self.build_latencies
                else 0.0
            ),
            "evaluations": self.evaluations,
            "signals_generated": self.signals_generated,
            "orders_generated": self.orders_generated,
            "fills": self.fills,
            "risk_rejections": self.risk_rejections,
            "last_nav": self.last_nav,
            "last_cash": self.last_cash,
            "reconciliation_ok": self.reconciliation_ok,
        }


class LiveFeedBuilder:
    """Chains M21→M20→M19→M18 to produce MarketDataSnapshot objects for M23.

    Designed to be reused across cycles. Each call to fetch_snapshot() is
    independent and deterministic given the same underlying provider response.

    Provider credentials: Yahoo Finance via yfinance requires no API key.
    """

    def __init__(self, config: LiveFeedConfig) -> None:
        self._config = config
        self._adapter = YahooFinanceSourceAdapter(
            id_map=config.id_map,
            name=config.provider_name,
            timezone=config.timezone,
        )
        quality_cfg = QualityConfig(max_staleness_days=config.max_staleness_days)
        self._builder = MarketDataSnapshotBuilder(
            normalizer=Normalizer(id_map=config.id_map),
            quality=MarketDataQualityEngine(quality_cfg),
            source=config.provider_name,
        )
        self._policy = PITPolicy(
            max_staleness_days=config.max_staleness_days,
            reject_look_ahead=True,
            fail_closed=config.pit_fail_closed,
        )
        self.metrics = FeedMetrics(provider=config.provider_name)

    # ── public API ────────────────────────────────────────────────────────────

    def fetch_snapshot(self, as_of: date) -> BuildResult | None:
        """Fetch real market observations and produce an M18 MarketDataSnapshot.

        Returns None if the snapshot cannot be built (provider failure or all
        securities rejected). Never fabricates data.

        Pipeline:
          _fetch_recent_records() — yfinance, restricted date window
            ↓  list[dict] Yahoo-shaped
          adapter.convert()       — M21 → M20 SourceMessages (offline, deterministic)
            ↓  list[SourceMessage]
          _extract_observation_payloads() — filter OBSERVATION messages
            ↓  list[dict] canonical payloads
          builder.build()         — M19 normalize + quality + PIT → M18 snapshot
            ↓  BuildResult | SnapshotBuildError
        """
        universe = list(self._config.universe)
        t0 = time.monotonic()
        self.metrics.requests += 1

        # ── M21: fetch recent records ─────────────────────────────────────────
        try:
            records = self._fetch_recent_records(universe, as_of)
            fetch_s = time.monotonic() - t0
            self.metrics.fetch_latencies.append(fetch_s)
            self.metrics.successful_responses += 1
        except Exception:
            self.metrics.failed_responses += 1
            self.metrics.snapshots_rejected += 1
            return None

        if not records:
            self.metrics.failed_responses += 1
            self.metrics.snapshots_rejected += 1
            return None

        # ── M20: SourceAdapter conversion (offline, deterministic) ────────────
        messages = self._adapter.convert(records, as_of)
        raw_payloads = self._extract_observation_payloads(messages)

        # ── M19 + M18: normalize → quality → PIT → snapshot ─────────────────
        t1 = time.monotonic()
        result = self._build_from_payloads(raw_payloads, as_of)
        build_s = time.monotonic() - t1
        self.metrics.build_latencies.append(build_s)

        return result

    def fetch_snapshot_from_records(self, records: list[dict], as_of: date) -> BuildResult | None:
        """Offline-testable entry point: converts caller-supplied Yahoo-shaped dicts.

        Identical pipeline to fetch_snapshot() except the yfinance call is
        replaced by the caller's fixture records. Used by integration tests.
        """
        messages = self._adapter.convert(records, as_of)
        raw_payloads = self._extract_observation_payloads(messages)
        return self._build_from_payloads(raw_payloads, as_of)

    # ── internals ─────────────────────────────────────────────────────────────

    def _fetch_recent_records(self, tickers: list[str], as_of: date) -> list[dict]:
        """Fetch last fetch_window_days of Yahoo Finance data for given tickers.

        Uses yfinance with a narrow date window rather than full history —
        the M21 adapter's full fetch() goes back to 1990 which is wasteful
        for a monthly paper-trading feed. The convert() method handles all
        schema translation.

        Returns Yahoo-shaped dicts: symbol/date/open/high/low/close/adj_close/volume/...
        """
        try:
            import yfinance as yf
        except ImportError:
            raise RuntimeError("yfinance not installed — pip install yfinance")

        window = self._config.fetch_window_days
        start = (as_of - timedelta(days=window)).isoformat()
        end = (as_of + timedelta(days=1)).isoformat()  # yfinance end is exclusive

        records: list[dict] = []
        for ticker in tickers:
            try:
                df = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False)
                if df is None or df.empty:
                    continue
                for row_date, row in df.iterrows():
                    d = row_date.date() if hasattr(row_date, "date") else row_date
                    if d > as_of:
                        continue
                    records.append(
                        {
                            "symbol": ticker,
                            "date": d.isoformat(),
                            "open": float(row.get("Open", 0) or 0),
                            "high": float(row.get("High", 0) or 0),
                            "low": float(row.get("Low", 0) or 0),
                            "close": float(row.get("Close", 0) or 0),
                            "adj_close": float(row.get("Adj Close", row.get("Close", 0)) or 0),
                            "volume": float(row.get("Volume", 0) or 0),
                            "dividends": float(row.get("Dividends", 0) or 0),
                            "stock_splits": float(row.get("Stock Splits", 0) or 0),
                        }
                    )
            except Exception:
                continue
        return records

    def _build_from_payloads(self, raw_payloads: list[dict], as_of: date) -> BuildResult | None:
        """Shared build path for both fetch_snapshot() and fetch_snapshot_from_records().

        M19 normalize → quality → PIT → M18 snapshot.
        Returns None if no spots were produced (all observations rejected or empty input).
        """
        self.metrics.observations_received += len(raw_payloads)
        try:
            result = self._builder.build(as_of=as_of, raw=raw_payloads, policy=self._policy)
        except SnapshotBuildError:
            self.metrics.snapshots_rejected += 1
            return None

        # Gate on empty spots — no fabricated snapshots
        if not result.snapshot.spots:
            self.metrics.snapshots_rejected += 1
            return None

        # Update metrics from diagnostics
        n_accepted = len(result.observations)
        n_rejected = len(raw_payloads) - n_accepted
        self.metrics.observations_rejected += n_rejected
        for diag in result.diagnostics:
            d_str = str(diag).lower()
            if "look_ahead" in d_str or "look-ahead" in d_str:
                self.metrics.pit_violations += 1
            elif "stale" in d_str:
                self.metrics.stale_observations += 1

        # Track which universe members are absent from snapshot
        universe = list(self._config.universe)
        present = set(result.snapshot.spots.keys())
        missing = [sid for sid in universe if sid not in present]
        if missing:
            self.metrics.missing_securities.extend(missing)

        self.metrics.snapshots_created += 1
        return result

    @staticmethod
    def _extract_observation_payloads(messages) -> list[dict]:
        """Extract payloads from OBSERVATION messages only (skip REFERENCE etc.)."""
        return [msg.payload for msg in messages if msg.msg_type == MessageType.OBSERVATION]
