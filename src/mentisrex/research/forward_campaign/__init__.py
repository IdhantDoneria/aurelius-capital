"""Forward paper-trading campaign infrastructure (M25 / M26).

Provides isolated PAPER_FORWARD operating mode with:
  - Deterministic cycle identity
  - Immutable sealed per-cycle records
  - Duplicate-cycle prevention
  - Forward performance ledger
  - Provider-revision-safe evidence storage
  - Restart / idempotency guarantees
  - No contamination from SIMULATION / BACKTEST / REPLAY state
  - Automated operational runner with health gate (M26)
"""

from mentisrex.research.forward_campaign.record import (
    CycleStatus,
    ForwardCycleRecord,
    make_forward_cycle_id,
)
from mentisrex.research.forward_campaign.ledger import ForwardLedger
from mentisrex.research.forward_campaign.campaign import ForwardCampaign, CampaignConfig
from mentisrex.research.forward_campaign.runner import ForwardOperationsRunner, RunnerConfig
from mentisrex.research.forward_campaign.benchmark import (
    BenchmarkCycleRecord,
    BenchmarkLedger,
    BenchmarkPortfolio,
    BenchmarkPerformanceSummary,
    fetch_spy_price,
)
from mentisrex.research.forward_campaign.evidence_report import (
    BacktestSnapshot,
    CycleComparison,
    ForwardEvidenceReport,
    EvidenceReportBuilder,
)
from mentisrex.research.forward_campaign.alpaca_execution import (
    AlpacaOrderExecution,
    CycleExecutionSummary,
    AlpacaCycleExecutionRecord,
    AlpacaExecutionLedger,
    AlpacaCycleExecutor,
    ForwardVsBacktestComparison,
    build_forward_vs_backtest_comparison,
)

from mentisrex.research.forward_campaign.data_quality import (
    DataRisks,
    DataQualityReport,
    check_snapshot_quality,
    check_universe_pit_risks,
)

__all__ = [
    # M25 / M26
    "CycleStatus",
    "ForwardCycleRecord",
    "ForwardLedger",
    "ForwardCampaign",
    "CampaignConfig",
    "ForwardOperationsRunner",
    "RunnerConfig",
    "make_forward_cycle_id",
    # M27 — benchmark
    "BenchmarkCycleRecord",
    "BenchmarkLedger",
    "BenchmarkPortfolio",
    "BenchmarkPerformanceSummary",
    "fetch_spy_price",
    # M27 — evidence report
    "BacktestSnapshot",
    "CycleComparison",
    "ForwardEvidenceReport",
    "EvidenceReportBuilder",
    # M29 — Alpaca execution quality
    "AlpacaOrderExecution",
    "CycleExecutionSummary",
    "AlpacaCycleExecutionRecord",
    "AlpacaExecutionLedger",
    "AlpacaCycleExecutor",
    "ForwardVsBacktestComparison",
    "build_forward_vs_backtest_comparison",
    # M30 — data quality
    "DataRisks",
    "DataQualityReport",
    "check_snapshot_quality",
    "check_universe_pit_risks",
]
