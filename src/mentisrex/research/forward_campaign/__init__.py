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

from mentisrex.research.forward_campaign.alpaca_execution import (
    AlpacaCycleExecutionRecord,
    AlpacaCycleExecutor,
    AlpacaExecutionLedger,
    AlpacaOrderExecution,
    CycleExecutionSummary,
    ForwardVsBacktestComparison,
    build_forward_vs_backtest_comparison,
)
from mentisrex.research.forward_campaign.benchmark import (
    BenchmarkCycleRecord,
    BenchmarkLedger,
    BenchmarkPerformanceSummary,
    BenchmarkPortfolio,
    fetch_spy_price,
)
from mentisrex.research.forward_campaign.campaign import CampaignConfig, ForwardCampaign
from mentisrex.research.forward_campaign.data_quality import (
    DataQualityReport,
    DataRisks,
    check_snapshot_quality,
    check_universe_pit_risks,
)
from mentisrex.research.forward_campaign.evidence_report import (
    BacktestSnapshot,
    CycleComparison,
    EvidenceReportBuilder,
    ForwardEvidenceReport,
)
from mentisrex.research.forward_campaign.ledger import ForwardLedger
from mentisrex.research.forward_campaign.record import (
    CycleStatus,
    ForwardCycleRecord,
    make_forward_cycle_id,
)
from mentisrex.research.forward_campaign.runner import ForwardOperationsRunner, RunnerConfig

__all__ = [
    "AlpacaCycleExecutionRecord",
    "AlpacaCycleExecutor",
    "AlpacaExecutionLedger",
    # M29 — Alpaca execution quality
    "AlpacaOrderExecution",
    # M27 — evidence report
    "BacktestSnapshot",
    # M27 — benchmark
    "BenchmarkCycleRecord",
    "BenchmarkLedger",
    "BenchmarkPerformanceSummary",
    "BenchmarkPortfolio",
    "CampaignConfig",
    "CycleComparison",
    "CycleExecutionSummary",
    # M25 / M26
    "CycleStatus",
    "DataQualityReport",
    # M30 — data quality
    "DataRisks",
    "EvidenceReportBuilder",
    "ForwardCampaign",
    "ForwardCycleRecord",
    "ForwardEvidenceReport",
    "ForwardLedger",
    "ForwardOperationsRunner",
    "ForwardVsBacktestComparison",
    "RunnerConfig",
    "build_forward_vs_backtest_comparison",
    "check_snapshot_quality",
    "check_universe_pit_risks",
    "fetch_spy_price",
    "make_forward_cycle_id",
]
