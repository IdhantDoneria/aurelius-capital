"""Forward evidence report — strategy vs benchmark vs backtest (M27).

Produces the M27 FORWARD EVIDENCE REPORT comparing:
  - Strategy forward performance (from ForwardLedger)
  - Benchmark performance (from BenchmarkLedger)
  - Relative (excess) performance
  - Backtest expectations (from M9/SIM validation artifact)

Statistical discipline:
  All statistics are explicitly labelled INSUFFICIENT_SAMPLE when the sample
  size is below the threshold for meaningful inference.  This module must
  never manufacture confidence from small samples.

Evidence milestones (not guarantees):
  1 cycle   : Operational evidence only.
  2–3 cycles: Early diagnostic only.
  6 cycles  : Preliminary forward-performance diagnostic.
  12 cycles : First serious annual comparison.
  24+ cycles: Substantially stronger evidence base.

Research-data isolation:
  Forward observations must NOT automatically enter backtest datasets,
  strategy optimization, parameter fitting, or model training.
  The forward campaign is an out-of-sample evaluation.  Importing forward
  observations into research requires an explicit, documented action after
  the evaluation period is considered closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from mentisrex.research.forward_campaign.benchmark import (
    BenchmarkLedger,
    BenchmarkPerformanceSummary,
)
from mentisrex.research.forward_campaign.ledger import (
    ForwardLedger,
    ForwardPerformanceSummary,
)
from mentisrex.research.forward_campaign.record import CycleStatus

# ── evidence stage thresholds ─────────────────────────────────────────────────

_STAGE_DESCRIPTIONS = {
    0: "NO_OBSERVATIONS — no forward evidence collected yet",
    1: "OPERATIONAL_EVIDENCE_ONLY — system confirmed operational; n=1",
    2: "EARLY_DIAGNOSTIC_ONLY — n=2; insufficient for performance inference",
    3: "EARLY_DIAGNOSTIC_ONLY — n=3; insufficient for performance inference",
    6: "PRELIMINARY_DIAGNOSTIC — n=6; preliminary forward-performance diagnostic",
    12: "FIRST_ANNUAL_COMPARISON — n=12; first serious forward-vs-backtest comparison",
    24: "STRONGER_EVIDENCE_BASE — n>=24; substantially stronger evidence base",
}


def _evidence_stage(n: int) -> str:
    if n == 0:
        return _STAGE_DESCRIPTIONS[0]
    if n == 1:
        return _STAGE_DESCRIPTIONS[1]
    if n <= 3:
        return _STAGE_DESCRIPTIONS[2]
    if n < 6:
        return _STAGE_DESCRIPTIONS[2]
    if n < 12:
        return _STAGE_DESCRIPTIONS[6]
    if n < 24:
        return _STAGE_DESCRIPTIONS[12]
    return _STAGE_DESCRIPTIONS[24]


_INSUFFICIENT_MSG = (
    "INSUFFICIENT SAMPLE — forward observations are too few for "
    "statistically meaningful performance inference."
)


# ── M9/SIM backtest snapshot ──────────────────────────────────────────────────


@dataclass(frozen=True)
class BacktestSnapshot:
    """Immutable snapshot of M9 backtest expectations for ew-momentum-exp.

    Source: data/validation/SIM/validation_report.json
    Validation artifact: 696a411bed6731a997c399584bfa9c4f
    n_observations: 729 daily observations (~3 years)
    Period: covered by the SIM validation experiment.

    These metrics are point-in-time as of the M9 validation run and must
    NOT be recalibrated using forward results.  Forward results must NOT
    feed back into the backtest.
    """

    manifest_hash: str = "696a411bed6731a997c399584bfa9c4f"
    experiment_id: str = "SIM"
    overall_verdict: str = "PASS"
    confidence_score: float = 88.1
    n_observations: int = 729  # daily observations
    sharpe_annualized: float = 2.119975
    mean_daily_return: float = 0.000424
    std_daily_return: float = 0.003176
    annualized_return: float = 0.10687  # mean_daily * 252
    annualized_volatility: float = 0.05042  # std_daily * sqrt(252)
    p_value: float = 0.000332
    annual_turnover: float = 0.467
    num_trades: int = 240
    universe: str = "AAPL,MSFT,GOOGL,AMZN,META,NVDA,TSLA,JPM,JNJ,V (10 fixed)"
    strategy_id: str = "ew-momentum-exp"
    strategy_version: str = "1.0.0"
    strategy_fingerprint: str = "b69961b65bab226a500d71f45709945b"
    data_limitation: str = (
        "SIM backtest used synthetic/simulation data (M9 validation framework). "
        "Not equivalent to live institutional data.  Forward data must NOT be "
        "used to recalibrate these metrics."
    )

    @classmethod
    def load(cls) -> BacktestSnapshot:
        """Load from canonical SIM validation report file."""
        try:
            import json
            from pathlib import Path

            repo_root = Path(__file__).resolve().parent.parent.parent.parent.parent
            report_path = repo_root / "data" / "validation" / "SIM" / "validation_report.json"
            if report_path.exists():
                d = json.loads(report_path.read_text())
                sig = d.get("statistical_summary", {}).get("significance", {})
                d.get("capacity_summary", {}).get("capacity", {})
                cap_turn = d.get("capacity_summary", {}).get("turnover", {})
                meta = d.get("execution_metadata", {})
                sharpe = sig.get("sharpe", cls.sharpe_annualized)
                mean_d = sig.get("mean", cls.mean_daily_return)
                std_d = sig.get("std", cls.std_daily_return)
                return cls(
                    manifest_hash=d.get("manifest_hash", cls.manifest_hash),
                    experiment_id=meta.get("experiment_id", cls.experiment_id),
                    overall_verdict=d.get("overall_verdict", cls.overall_verdict),
                    confidence_score=d.get("confidence_score", cls.confidence_score),
                    n_observations=meta.get("n_observations", cls.n_observations),
                    sharpe_annualized=sharpe,
                    mean_daily_return=mean_d,
                    std_daily_return=std_d,
                    annualized_return=mean_d * 252,
                    annualized_volatility=std_d * (252**0.5),
                    p_value=sig.get("p_value", cls.p_value),
                    annual_turnover=cap_turn.get("annual_turnover", cls.annual_turnover),
                    num_trades=cap_turn.get("num_trades", cls.num_trades),
                )
        except Exception:
            pass
        return cls()


# ── per-cycle comparison ──────────────────────────────────────────────────────


@dataclass
class CycleComparison:
    """Strategy vs benchmark for a single cycle."""

    cycle_id: str
    evaluation_date: date | None
    strategy_return: float
    benchmark_return: float
    excess_return: float  # strategy_return - benchmark_return
    strategy_nav: float
    benchmark_nav: float
    strategy_cumulative_return: float
    benchmark_cumulative_return: float
    cumulative_excess_return: float


# ── main evidence report ──────────────────────────────────────────────────────


@dataclass
class ForwardEvidenceReport:
    """Complete M27 forward evidence report.

    Sections:
      A. Strategy metadata
      B. Forward observation inventory
      C. Strategy performance
      D. Benchmark performance
      E. Relative performance
      F. Data quality
      G. Backtest comparison
      H. Statistical status
    """

    # A. Strategy
    strategy_id: str = ""
    strategy_version: str = ""
    strategy_fingerprint: str = ""
    universe: list = field(default_factory=list)
    initial_capital: float = 1_000_000.0

    # B. Forward observations
    cycles_completed: int = 0
    cycles_skipped: int = 0
    cycles_failed: int = 0
    latest_cycle_id: str = ""
    latest_as_of_date: date | None = None
    first_as_of_date: date | None = None

    # C. Strategy performance
    strategy_current_nav: float = 0.0
    strategy_cumulative_return: float = 0.0
    strategy_monthly_returns: list = field(default_factory=list)
    strategy_max_drawdown: float = 0.0
    strategy_annualized_return: float | None = None
    strategy_annualized_return_label: str = "INSUFFICIENT_SAMPLE"
    strategy_sharpe: float | None = None
    strategy_sharpe_label: str = "INSUFFICIENT_SAMPLE"
    strategy_total_turnover: float = 0.0
    strategy_total_fills: int = 0

    # D. Benchmark performance
    benchmark_symbol: str = "SPY"
    benchmark_current_nav: float = 0.0
    benchmark_cumulative_return: float = 0.0
    benchmark_monthly_returns: list = field(default_factory=list)
    benchmark_max_drawdown: float = 0.0
    benchmark_annualized_return: float | None = None
    benchmark_annualized_return_label: str = "INSUFFICIENT_SAMPLE"
    benchmark_inception_date: date | None = None
    benchmark_inception_price: float = 0.0
    benchmark_data_limitation: str = ""

    # E. Relative performance
    cycle_comparisons: list = field(default_factory=list)  # list[CycleComparison]
    cumulative_excess_return: float = 0.0
    excess_return_label: str = "INSUFFICIENT_SAMPLE"

    # F. Data quality
    provider: str = "yahoo_finance"
    total_observations_accepted: int = 0
    total_observations_rejected: int = 0
    total_pit_violations: int = 0
    total_missing_securities: list = field(default_factory=list)

    # G. Backtest comparison
    backtest: BacktestSnapshot | None = None
    backtest_vs_forward: dict = field(default_factory=dict)

    # H. Statistical status
    n_genuine_forward_observations: int = 0
    evidence_stage: str = ""
    insufficient_sample: bool = True
    statistical_status_message: str = _INSUFFICIENT_MSG

    # Governance
    real_market_data: str = "YES"
    genuine_forward_observation: str = "YES"
    paper_execution: str = "YES"
    live_execution: str = "NO"
    real_capital: str = "NO"
    strategy_modified: str = "NO"
    research_data_isolated: str = "YES"

    # M29 — Alpaca execution quality
    alpaca_execution_cycles: int = 0  # cycles with Alpaca paper execution
    alpaca_orders_submitted: int = 0
    alpaca_orders_filled: int = 0
    alpaca_fill_rate: float | None = None  # None if no Alpaca cycles yet
    avg_slippage_bps: float | None = None
    avg_execution_latency_ms: float | None = None
    execution_quality_label: str = "NO_ALPACA_EXECUTION"
    reconciliation_pass_rate: float | None = None
    execution_quality: dict = field(default_factory=dict)  # raw summary dict

    # M29 — structured forward vs backtest comparison
    forward_vs_backtest: object | None = None  # ForwardVsBacktestComparison

    def to_dict(self) -> dict:
        import dataclasses as dc

        d = {}
        for f in dc.fields(self):
            v = getattr(self, f.name)
            if isinstance(v, date) and not isinstance(v, datetime):
                d[f.name] = v.isoformat()
            elif dc.is_dataclass(v) and not isinstance(v, type):
                d[f.name] = dc.asdict(v)
            elif isinstance(v, list):
                out = []
                for item in v:
                    if dc.is_dataclass(item) and not isinstance(item, type):
                        out.append(dc.asdict(item))
                    elif isinstance(item, date) and not isinstance(item, datetime):
                        out.append(item.isoformat())
                    else:
                        out.append(item)
                d[f.name] = out
            else:
                d[f.name] = v
        return d

    def print_summary(self) -> None:
        """Print human-readable evidence report to stdout."""
        print()
        print("=" * 70)
        print("MENTISREX — M27 FORWARD EVIDENCE REPORT")
        print("=" * 70)

        print()
        print("A. STRATEGY")
        print(f"  strategy_id         : {self.strategy_id}")
        print(f"  strategy_version    : {self.strategy_version}")
        print(f"  strategy_fingerprint: {self.strategy_fingerprint}")
        print(
            f"  universe            : {', '.join(self.universe[:5])}{'...' if len(self.universe) > 5 else ''}"
        )
        print(f"  initial_capital     : ${self.initial_capital:,.0f}")

        print()
        print("B. FORWARD OBSERVATIONS")
        print(f"  cycles_completed    : {self.cycles_completed}")
        print(f"  cycles_skipped      : {self.cycles_skipped}")
        print(f"  cycles_failed       : {self.cycles_failed}")
        print(f"  first_observation   : {self.first_as_of_date}")
        print(f"  latest_observation  : {self.latest_as_of_date}")
        print(f"  latest_cycle_id     : {self.latest_cycle_id}")

        print()
        print("C. STRATEGY PERFORMANCE")
        print(f"  current_nav         : ${self.strategy_current_nav:,.2f}")
        print(f"  cumulative_return   : {self.strategy_cumulative_return:.4%}")
        print(f"  max_drawdown        : {self.strategy_max_drawdown:.4%}")
        ann = (
            f"{self.strategy_annualized_return:.4%}"
            if self.strategy_annualized_return is not None
            else "N/A"
        )
        print(f"  annualized_return   : {ann} [{self.strategy_annualized_return_label}]")
        sharpe = f"{self.strategy_sharpe:.3f}" if self.strategy_sharpe is not None else "N/A"
        print(f"  sharpe              : {sharpe} [{self.strategy_sharpe_label}]")
        print(f"  total_fills         : {self.strategy_total_fills}")

        print()
        print("D. BENCHMARK PERFORMANCE (SPY price return, no dividends)")
        print(f"  benchmark_symbol    : {self.benchmark_symbol}")
        print(f"  inception_date      : {self.benchmark_inception_date}")
        print(f"  inception_price     : ${self.benchmark_inception_price:,.2f}")
        print(f"  current_nav         : ${self.benchmark_current_nav:,.2f}")
        print(f"  cumulative_return   : {self.benchmark_cumulative_return:.4%}")
        print(f"  max_drawdown        : {self.benchmark_max_drawdown:.4%}")
        bann = (
            f"{self.benchmark_annualized_return:.4%}"
            if self.benchmark_annualized_return is not None
            else "N/A"
        )
        print(f"  annualized_return   : {bann} [{self.benchmark_annualized_return_label}]")
        print(f"  data_limitation     : {self.benchmark_data_limitation[:80]}...")

        print()
        print("E. RELATIVE PERFORMANCE")
        print(
            f"  cumulative_excess   : {self.cumulative_excess_return:.4%} [{self.excess_return_label}]"
        )
        if self.cycle_comparisons:
            print("  per-cycle summary:")
            for cc in self.cycle_comparisons:
                if isinstance(cc, CycleComparison):
                    cid = cc.cycle_id
                    sr = cc.strategy_return
                    br = cc.benchmark_return
                    er = cc.excess_return
                elif isinstance(cc, dict):
                    cid = cc.get("cycle_id", "?")
                    sr = cc.get("strategy_return", 0)
                    br = cc.get("benchmark_return", 0)
                    er = cc.get("excess_return", 0)
                else:
                    continue
                print(f"    {cid}  strategy={sr:.4%}  benchmark={br:.4%}  excess={er:+.4%}")

        print()
        print("F. DATA QUALITY")
        print(f"  provider            : {self.provider}")
        print(f"  observations_ok     : {self.total_observations_accepted}")
        print(f"  observations_rej    : {self.total_observations_rejected}")
        print(f"  pit_violations      : {self.total_pit_violations}")

        print()
        print("G. BACKTEST COMPARISON (M9 / SIM validation artifact)")
        if self.backtest:
            bt = self.backtest
            print(f"  manifest_hash       : {bt.manifest_hash}")
            print(f"  n_observations      : {bt.n_observations} daily")
            print(f"  backtest_sharpe     : {bt.sharpe_annualized:.3f} (annualized)")
            print(f"  backtest_ann_return : {bt.annualized_return:.4%}")
            print(f"  backtest_ann_vol    : {bt.annualized_volatility:.4%}")
            print(f"  p_value             : {bt.p_value:.6f}")
            print(f"  data_limitation     : {bt.data_limitation[:70]}...")
        if self.backtest_vs_forward:
            print(
                f"  forward_sharpe      : {self.backtest_vs_forward.get('forward_sharpe', 'N/A')}"
            )
            print(
                f"  forward_ann_return  : {self.backtest_vs_forward.get('forward_ann_return', 'N/A')}"
            )
            print(f"  note                : {self.backtest_vs_forward.get('note', '')}")

        print()
        print("H. STATISTICAL STATUS")
        print(f"  n_genuine_obs       : {self.n_genuine_forward_observations}")
        print(f"  evidence_stage      : {self.evidence_stage}")
        print(f"  *** {self.statistical_status_message} ***")

        print()
        print("GOVERNANCE")
        print(f"  REAL MARKET DATA            : {self.real_market_data}")
        print(f"  GENUINE FORWARD OBSERVATION : {self.genuine_forward_observation}")
        print(f"  PAPER EXECUTION             : {self.paper_execution}")
        print(f"  LIVE EXECUTION              : {self.live_execution}")
        print(f"  REAL CAPITAL                : {self.real_capital}")
        print(f"  STRATEGY MODIFIED           : {self.strategy_modified}")
        print(f"  RESEARCH DATA ISOLATED      : {self.research_data_isolated}")
        print("=" * 70)


# ── report builder ────────────────────────────────────────────────────────────


class EvidenceReportBuilder:
    """Build a ForwardEvidenceReport from ledger + benchmark + backtest.

    Usage:
        builder = EvidenceReportBuilder(
            campaign_dir=Path("data/forward_campaign/..."),
            strategy_id="ew-momentum-exp",
            strategy_version="1.0.0",
            strategy_fingerprint="b69961b65bab226a500d71f45709945b",
            universe=UNIVERSE,
            initial_capital=1_000_000.0,
        )
        report = builder.build()
        report.print_summary()
    """

    def __init__(
        self,
        campaign_dir: Path,
        strategy_id: str,
        strategy_version: str,
        strategy_fingerprint: str,
        universe: list,
        initial_capital: float = 1_000_000.0,
    ) -> None:
        self._campaign_dir = Path(campaign_dir)
        self._fwd_ledger = ForwardLedger(self._campaign_dir)
        self._bmk_ledger = BenchmarkLedger(self._campaign_dir)
        self._strategy_id = strategy_id
        self._strategy_version = strategy_version
        self._strategy_fingerprint = strategy_fingerprint
        self._universe = list(universe)
        self._initial_capital = initial_capital

    def build(
        self, *, load_backtest: bool = True, include_alpaca_execution: bool = True
    ) -> ForwardEvidenceReport:
        """Assemble the full evidence report."""
        fwd_summary: ForwardPerformanceSummary = self._fwd_ledger.performance_summary()
        bmk_summary: BenchmarkPerformanceSummary = self._bmk_ledger.performance_summary()
        backtest = BacktestSnapshot.load() if load_backtest else BacktestSnapshot()

        # all successful cycles from forward ledger
        all_fwd = [c for c in self._fwd_ledger.list_cycles() if c.status == CycleStatus.SUCCESS]
        all_bmk = {c.cycle_id: c for c in self._bmk_ledger.list_cycles() if c.status == "SUCCESS"}
        n_genuine = len(all_fwd)

        # per-cycle comparison
        comparisons: list[CycleComparison] = []
        strat_nav = self._initial_capital
        cumulative_excess = 0.0

        for fc in all_fwd:
            bc = all_bmk.get(fc.cycle_id)
            strat_ret = fc.gross_return
            bmk_ret = bc.period_return if bc else 0.0
            excess = strat_ret - bmk_ret
            strat_nav = fc.ending_nav
            bmk_nav_val = bc.ending_nav if bc else self._initial_capital
            strat_cum = (
                strat_nav / self._initial_capital - 1.0 if self._initial_capital > 0 else 0.0
            )
            bmk_cum = (
                bmk_nav_val / self._initial_capital - 1.0 if self._initial_capital > 0 else 0.0
            )
            cumulative_excess = strat_cum - bmk_cum

            comparisons.append(
                CycleComparison(
                    cycle_id=fc.cycle_id,
                    evaluation_date=fc.evaluation_date,
                    strategy_return=strat_ret,
                    benchmark_return=bmk_ret,
                    excess_return=excess,
                    strategy_nav=strat_nav,
                    benchmark_nav=bmk_nav_val,
                    strategy_cumulative_return=strat_cum,
                    benchmark_cumulative_return=bmk_cum,
                    cumulative_excess_return=cumulative_excess,
                )
            )

        # data quality aggregation
        all_fwd_all = self._fwd_ledger.list_cycles()
        total_accepted = sum(
            c.observations_accepted for c in all_fwd_all if c.status == CycleStatus.SUCCESS
        )
        total_rejected = sum(
            c.observations_rejected for c in all_fwd_all if c.status == CycleStatus.SUCCESS
        )
        total_pit = sum(c.pit_violations for c in all_fwd_all if c.status == CycleStatus.SUCCESS)
        missing: list = []
        for c in all_fwd_all:
            missing.extend(c.missing_securities)

        # backtest comparison (labels only; no recalibration)
        bt_vs_fwd: dict = {
            "note": (
                "n_genuine_forward_observations is INSUFFICIENT to compare "
                f"against backtest ({n_genuine} cycle(s) vs {backtest.n_observations} "
                "daily backtest observations).  Comparison will be meaningful "
                "at n >= 12 forward cycles."
            )
            if n_genuine < 12
            else ("n >= 12 forward cycles — preliminary comparison possible."),
            "forward_sharpe": (
                f"{fwd_summary.sharpe:.3f}"
                if fwd_summary.sharpe is not None
                else f"N/A [{fwd_summary.sharpe_label}]"
            ),
            "forward_ann_return": (
                f"{fwd_summary.annualized_return:.4%}"
                if fwd_summary.annualized_return is not None
                else f"N/A [{fwd_summary.annualized_return_label}]"
            ),
            "backtest_sharpe": f"{backtest.sharpe_annualized:.3f}",
            "backtest_ann_return": f"{backtest.annualized_return:.4%}",
            "comparison_validity": ("INSUFFICIENT_SAMPLE" if n_genuine < 12 else "PRELIMINARY"),
        }

        # latest cycle metadata
        latest = self._fwd_ledger.latest_cycle()
        first = all_fwd[0] if all_fwd else None

        # evidence stage
        stage = _evidence_stage(n_genuine)
        insufficient = n_genuine < 12
        stat_msg = (
            f"n={n_genuine} monthly forward observations are insufficient to "
            "establish economic validity."
            if n_genuine < 12
            else f"n={n_genuine} monthly forward observations: preliminary annual "
            "comparison possible.  Economic validity not yet established."
        )

        # M29 — Alpaca execution quality
        exec_quality: dict = {}
        exec_cycles = 0
        exec_orders_submitted = 0
        exec_orders_filled = 0
        exec_fill_rate: float | None = None
        exec_avg_slippage: float | None = None
        exec_avg_latency: float | None = None
        exec_quality_label = "NO_ALPACA_EXECUTION"
        exec_recon_pass_rate: float | None = None
        fvb_comparison = None

        if include_alpaca_execution:
            try:
                from mentisrex.research.forward_campaign.alpaca_execution import (
                    AlpacaExecutionLedger,
                    build_forward_vs_backtest_comparison,
                )

                exec_ledger = AlpacaExecutionLedger(self._campaign_dir)
                exec_quality = exec_ledger.execution_quality_summary()
                exec_cycles = exec_quality.get("n_cycles", 0)
                exec_orders_submitted = exec_quality.get("total_orders_submitted", 0)
                exec_orders_filled = exec_quality.get("total_orders_filled", 0)
                fr = exec_quality.get("overall_fill_rate", "UNAVAILABLE")
                exec_fill_rate = float(fr) if isinstance(fr, (int, float)) else None
                sl = exec_quality.get("avg_slippage_bps", "UNAVAILABLE")
                exec_avg_slippage = float(sl) if isinstance(sl, (int, float)) else None
                lt = exec_quality.get("avg_latency_ms", "UNAVAILABLE")
                exec_avg_latency = float(lt) if isinstance(lt, (int, float)) else None
                rp = exec_quality.get("reconciliation_pass_rate", "UNAVAILABLE")
                exec_recon_pass_rate = float(rp) if isinstance(rp, (int, float)) else None
                exec_quality_label = "ALPACA_PAPER" if exec_cycles > 0 else "NO_ALPACA_EXECUTION"
                fvb_comparison = build_forward_vs_backtest_comparison(backtest, fwd_summary)
            except Exception:
                pass

        return ForwardEvidenceReport(
            # A
            strategy_id=self._strategy_id,
            strategy_version=self._strategy_version,
            strategy_fingerprint=self._strategy_fingerprint,
            universe=self._universe,
            initial_capital=self._initial_capital,
            # B
            cycles_completed=fwd_summary.n_successful_cycles,
            cycles_skipped=fwd_summary.n_skipped_cycles,
            cycles_failed=fwd_summary.n_failed_cycles,
            latest_cycle_id=latest.cycle_id if latest else "",
            latest_as_of_date=latest.knowledge_as_of if latest else None,
            first_as_of_date=first.knowledge_as_of if first else None,
            # C
            strategy_current_nav=fwd_summary.current_nav or self._initial_capital,
            strategy_cumulative_return=fwd_summary.cumulative_return,
            strategy_monthly_returns=list(fwd_summary.monthly_returns),
            strategy_max_drawdown=fwd_summary.max_drawdown,
            strategy_annualized_return=fwd_summary.annualized_return,
            strategy_annualized_return_label=fwd_summary.annualized_return_label,
            strategy_sharpe=fwd_summary.sharpe,
            strategy_sharpe_label=fwd_summary.sharpe_label,
            strategy_total_turnover=fwd_summary.total_turnover,
            strategy_total_fills=fwd_summary.total_fills,
            # D
            benchmark_symbol=bmk_summary.benchmark_symbol,
            benchmark_current_nav=bmk_summary.current_nav or self._initial_capital,
            benchmark_cumulative_return=bmk_summary.cumulative_return,
            benchmark_monthly_returns=list(bmk_summary.monthly_returns),
            benchmark_max_drawdown=bmk_summary.max_drawdown,
            benchmark_annualized_return=bmk_summary.annualized_return,
            benchmark_annualized_return_label=bmk_summary.annualized_return_label,
            benchmark_inception_date=bmk_summary.inception_date,
            benchmark_inception_price=bmk_summary.inception_price,
            benchmark_data_limitation=bmk_summary.data_limitation,
            # E
            cycle_comparisons=comparisons,
            cumulative_excess_return=cumulative_excess if comparisons else 0.0,
            excess_return_label=("INSUFFICIENT_SAMPLE" if n_genuine < 6 else "ESTIMATED"),
            # F
            provider="yahoo_finance",
            total_observations_accepted=total_accepted,
            total_observations_rejected=total_rejected,
            total_pit_violations=total_pit,
            total_missing_securities=list(set(missing)),
            # G
            backtest=backtest,
            backtest_vs_forward=bt_vs_fwd,
            # H
            n_genuine_forward_observations=n_genuine,
            evidence_stage=stage,
            insufficient_sample=insufficient,
            statistical_status_message=stat_msg,
            # M29
            alpaca_execution_cycles=exec_cycles,
            alpaca_orders_submitted=exec_orders_submitted,
            alpaca_orders_filled=exec_orders_filled,
            alpaca_fill_rate=exec_fill_rate,
            avg_slippage_bps=exec_avg_slippage,
            avg_execution_latency_ms=exec_avg_latency,
            execution_quality_label=exec_quality_label,
            reconciliation_pass_rate=exec_recon_pass_rate,
            execution_quality=exec_quality,
            forward_vs_backtest=fvb_comparison,
        )


# import guard for type annotations
from datetime import datetime  # noqa: E402 — after dataclasses above
