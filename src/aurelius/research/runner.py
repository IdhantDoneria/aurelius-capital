"""ResearchRunner — idea to verdict in one call, everything recorded.

investigate() runs the pipeline: dataset fingerprint -> IS/OOS split ->
parameter-sensitivity grid -> multiple-testing-aware verdict -> store. It counts
every parameter combination as a trial so the data-mining correction is honest.
"""

from __future__ import annotations

import itertools
import random
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from aurelius.backtesting.config import BacktestConfig
from aurelius.backtesting.data.feed import BarData
from aurelius.backtesting.strategy.base import Strategy
from aurelius.core.logging import get_logger
from aurelius.research.models import (
    ExperimentRecord,
    Hypothesis,
    ValidationCriteria,
    ValidationReport,
    Verdict,
    dataset_fingerprint,
)
from aurelius.research.store import ResearchStore
from aurelius.research.validation import evaluate, parameter_sensitivity, train_test

logger = get_logger(__name__)

ParamFactory = Callable[[dict], Strategy]


class ResearchRunner:
    def __init__(self, store: ResearchStore, criteria: ValidationCriteria | None = None) -> None:
        self.store = store
        self.criteria = criteria or ValidationCriteria()

    def hypothesis(self, statement: str, rationale: str, researcher: str) -> Hypothesis:
        return self.store.record_hypothesis(statement, rationale, researcher)

    def investigate(
        self,
        hypothesis: Hypothesis,
        factory_from_params: ParamFactory,
        base_params: dict,
        bars: Sequence[BarData],
        config: BacktestConfig | None = None,
        param_grid: dict[str, list] | None = None,
        features_used: list[str] | None = None,
    ) -> ValidationReport:
        config = config or BacktestConfig()
        ts = sorted({b.timestamp for b in bars})
        symbols = sorted({b.symbol for b in bars})
        fingerprint = dataset_fingerprint(symbols, ts[0], ts[-1], len(bars))

        base_strategy = factory_from_params(base_params)
        dup = self.store.find_duplicate(fingerprint, base_strategy.name, 1, base_params)
        if dup:
            logger.warning("duplicate_experiment", existing_id=dup)

        prior_trials = self.store.trial_count(hypothesis.id)

        is_m, oos_m = train_test(
            lambda: factory_from_params(base_params), bars, config, train_frac=0.7
        )

        param_cv = None
        grid_size = 1
        if param_grid:
            grid_size = len(list(itertools.product(*param_grid.values())))
            sens = parameter_sensitivity(
                factory_from_params, param_grid, bars, config, train_frac=0.7
            )
            param_cv = sens.cv

        # Every parameter combination looked at is a trial; add prior history.
        n_trials = prior_trials + grid_size

        report = evaluate(is_m, oos_m, n_trials, self.criteria, param_cv)

        self.store.record_experiment(
            ExperimentRecord(
                id=str(uuid.uuid4()),
                hypothesis_id=hypothesis.id,
                researcher=hypothesis.researcher,
                created_at=datetime.now(UTC),
                dataset_version=fingerprint,
                strategy_name=base_strategy.name,
                strategy_version=1,
                features_used=features_used or [],
                params=base_params,
                report=report,
            )
        )

        status = {
            Verdict.ACCEPT: "confirmed",
            Verdict.REJECT: "rejected",
            Verdict.INCONCLUSIVE: "open",
        }[report.verdict]
        self.store.set_hypothesis_status(hypothesis.id, status)
        return report


# ── demonstration ─────────────────────────────────────────────────────────────

def research_config(**overrides) -> BacktestConfig:
    """Backtest config for research runs: a looser drawdown halt so a mediocre
    strategy runs to completion (and is judged on OOS) instead of tripping the
    live-trading circuit breaker mid-sample."""
    cfg = BacktestConfig(
        max_drawdown_halt=Decimal("0.60"),   # loose halt: judge on OOS, not a trip
        max_position_pct=Decimal("0.05"),     # conservative sizing keeps runs alive
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def synth_bars(
    symbols: list[str], days: int = 400, seed: int = 7, drift: float = 0.0008, vol: float = 0.005
) -> list[BarData]:
    """Deterministic synthetic OHLCV for demos/tests. Even-indexed names trend up."""
    rnd = random.Random(seed)
    t0 = datetime(2020, 1, 1, tzinfo=UTC)
    out: list[BarData] = []
    for si, s in enumerate(symbols):
        p = 100.0 + si * 8
        d = drift + drift * si  # all mildly trending, dispersed by name (winners/losers)
        for i in range(days):
            p = max(1.0, p * (1 + rnd.gauss(d, vol)))
            c = Decimal(str(round(p, 4)))
            out.append(
                BarData(
                    symbol=s,
                    timestamp=t0 + timedelta(days=i),
                    open=c,
                    high=c * Decimal("1.01"),
                    low=c * Decimal("0.99"),
                    close=c,
                    volume=Decimal("100000"),
                )
            )
    return out


def demo() -> ValidationReport:
    """Walk one hypothesis from idea to conclusion. Returns the verdict report."""
    from aurelius.research.templates import MeanReversionStrategy
    from aurelius.research.validation import select_features

    store = ResearchStore(":memory:")
    runner = ResearchRunner(store)
    bars = synth_bars(["AAA", "BBB"], days=400, drift=0.0006, vol=0.007)

    # Stage 1 — Hypothesis
    h = runner.hypothesis(
        statement="Short-term price dislocations mean-revert in these names.",
        rationale="Liquidity provision: fade z-score extremes, collect the snap-back.",
        researcher="jdoe",
    )

    # Stage 2 — Feature Selection (in-sample only, no leak)
    ts = sorted({b.timestamp for b in bars})
    cut = ts[int(len(ts) * 0.7)]
    train_bars = [b for b in bars if b.timestamp < cut]
    top = select_features(train_bars, horizon=5, top_n=3)

    # Stage 3-6 — Strategy, Backtest, Validation, Verdict.
    # A wide grid is honest: every combination we look at is a trial the
    # data-mining correction must pay for.
    report = runner.investigate(
        hypothesis=h,
        factory_from_params=lambda p: MeanReversionStrategy(allow_short=False, **p),
        base_params={"lookback": 20, "entry_z": 1.0, "exit_z": 0.25},
        bars=bars,
        config=research_config(),
        param_grid={"lookback": [10, 15, 20, 25, 30], "entry_z": [0.8, 1.0, 1.5]},
        features_used=[name for name, _ in top],
    )

    print("=" * 68)
    print(f"HYPOTHESIS: {h.statement}")
    print(f"  researcher={h.researcher}  rationale={h.rationale}")
    print(f"FEATURE SELECTION (in-sample IC): {[(n, round(ic, 3)) for n, ic in top]}")
    print("-" * 68)
    print(f"IS Sharpe   : {report.is_sharpe:.3f}")
    print(f"OOS Sharpe  : {report.oos_sharpe:.3f}")
    print(f"OOS return  : {report.oos_return:.2%}")
    print(f"OOS max DD  : {report.oos_max_drawdown:.2%}")
    print(f"OOS trades  : {report.oos_trades}")
    print(f"trials      : {report.n_trials}  (grid + prior)")
    print(f"adj p-value : {report.adjusted_pvalue:.3f}")
    cv_line = f"{report.param_cv:.2f}" if report.param_cv is not None else "n/a"
    print(f"param CV    : {cv_line}")
    print("-" * 68)
    print(f"VERDICT: {report.verdict.value.upper()}")
    for r in report.reasons:
        print(f"  - {r}")
    print(f"Rejected ideas on record: {len(store.rejected_ideas())}")
    print("=" * 68)
    store.close()
    return report


if __name__ == "__main__":
    demo()
