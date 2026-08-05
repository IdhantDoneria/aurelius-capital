"""Research framework tests: guards reject bad ideas, pipeline runs, store works."""

from __future__ import annotations

from aurelius.backtesting.analytics.performance import PerformanceMetrics
from aurelius.research import (
    ResearchRunner,
    ResearchStore,
    Verdict,
    research_config,
    synth_bars,
)
from aurelius.research.models import ValidationCriteria, bonferroni, sharpe_pvalue
from aurelius.research.templates import (
    FactorStrategy,
    MeanReversionStrategy,
    MomentumStrategy,
    OverlappingFactorStrategy,
    PairsStrategy,
)
from aurelius.research.validation import (
    evaluate,
    parameter_sensitivity,
    run_backtest,
    train_test,
    walk_forward,
)


def _metrics(sharpe, n=100, trades=50, ret=0.1, dd=-0.05):
    m = PerformanceMetrics()
    m.sharpe_ratio = sharpe
    m.total_return = ret
    m.max_drawdown = dd
    m.num_trades = trades
    m.daily_returns = [0.001] * n
    return m


# ── the guards: bad ideas must be rejected ────────────────────────────────────


def test_low_oos_sharpe_rejected():
    r = evaluate(_metrics(1.5), _metrics(0.1), n_trials=1)
    assert r.verdict is Verdict.REJECT
    assert any("Sharpe" in x for x in r.reasons)


def test_is_oos_decay_rejected():
    # Strong IS, weak-but-positive OOS -> overfit decay guard fires
    r = evaluate(_metrics(3.0), _metrics(0.6), n_trials=1)
    assert r.verdict is Verdict.REJECT
    assert any("overfit" in x for x in r.reasons)


def test_multiple_testing_rejects_marginal_edge():
    # A Sharpe that is significant at 1 trial is not after 500 trials
    solo = evaluate(_metrics(0.9), _metrics(0.9, n=120), n_trials=1)
    mined = evaluate(_metrics(0.9), _metrics(0.9, n=120), n_trials=500)
    assert mined.adjusted_pvalue > solo.adjusted_pvalue
    assert any("significant" in x for x in mined.reasons)


def test_fragile_parameters_rejected():
    r = evaluate(_metrics(1.0), _metrics(1.0, n=120), n_trials=1, param_cv=2.0)
    assert r.verdict is Verdict.REJECT
    assert any("fragile" in x for x in r.reasons)


def test_short_oos_is_inconclusive():
    r = evaluate(_metrics(1.0), _metrics(1.0, n=5), n_trials=1)
    assert r.verdict is Verdict.INCONCLUSIVE


def test_clean_edge_accepted():
    # Sharpe 1.4 over ~3yr (756 obs) is significant (t~2.4); survives every guard.
    crit = ValidationCriteria(min_trades=10)
    r = evaluate(
        _metrics(1.5), _metrics(1.4, n=756, trades=40), n_trials=1, param_cv=0.1, criteria=crit
    )
    assert r.verdict is Verdict.ACCEPT
    assert r.reasons == []


def test_bonferroni_monotonic():
    assert bonferroni(0.01, 10) == 0.1
    assert bonferroni(0.5, 100) == 1.0
    assert sharpe_pvalue(2.0, 252) < sharpe_pvalue(0.5, 252)


# ── templates run on the engine ───────────────────────────────────────────────


def test_all_templates_run():
    bars = synth_bars(["AAA", "BBB", "CCC", "DDD"], days=200)
    for factory in (
        lambda: MomentumStrategy(lookback=30),
        lambda: MeanReversionStrategy(lookback=20),
        lambda: FactorStrategy(lookback=30, rebalance_days=10),
        lambda: PairsStrategy("AAA", "BBB", lookback=30),
    ):
        m = run_backtest(factory, bars)
        assert isinstance(m, PerformanceMetrics)
        assert len(m.equity_curve) > 0


def test_equal_weight_parameter_and_run():
    """M1: equal_weight=True is reflected in parameters and the strategy runs
    end-to-end with max_position_pct=1.0 (strength IS the target NAV fraction)."""
    from decimal import Decimal
    from aurelius.backtesting.config import BacktestConfig

    # parameters dict carries the flag
    strat = FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10,
                           allow_short=True, equal_weight=True)
    assert strat.parameters["equal_weight"] is True

    # existing FactorStrategy without flag: equal_weight defaults False, backward-compat
    strat_old = FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10)
    assert strat_old.parameters["equal_weight"] is False

    # runs without error with max_position_pct=1.0
    bars = synth_bars(["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"], days=200, seed=42)
    cfg = BacktestConfig(max_drawdown_halt=Decimal("0.60"), max_position_pct=Decimal("1.0"))
    m = run_backtest(lambda: FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10,
                                            allow_short=True, equal_weight=True), bars, cfg)
    assert isinstance(m, PerformanceMetrics)
    assert len(m.equity_curve) > 0

    # long-only equal_weight runs too
    m2 = run_backtest(lambda: FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10,
                                             allow_short=False, equal_weight=True), bars, cfg)
    assert isinstance(m2, PerformanceMetrics)


def test_min_price_parameter_and_run():
    """M2: min_price filter reflected in parameters; backward-compat default 0.0.
    With a high min_price, low-price synth names are excluded from the cross-section."""
    from decimal import Decimal
    from aurelius.backtesting.config import BacktestConfig

    strat = FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10,
                           equal_weight=True, min_price=5.0)
    assert strat.parameters["min_price"] == 5.0

    strat_old = FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10)
    assert strat_old.parameters["min_price"] == 0.0  # backward-compat

    bars = synth_bars(["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"], days=200, seed=42)
    cfg = BacktestConfig(max_drawdown_halt=Decimal("0.60"), max_position_pct=Decimal("1.0"))

    # M2 runs end-to-end (synth prices ~$20-50 so filter doesn't starve universe)
    m = run_backtest(lambda: FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10,
                                            allow_short=True, equal_weight=True,
                                            min_price=5.0), bars, cfg)
    assert isinstance(m, PerformanceMetrics)
    assert len(m.equity_curve) > 0

    # Very high min_price starves cross-section — must not crash, just fewer/no trades
    m_starved = run_backtest(
        lambda: FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10,
                               equal_weight=True, min_price=1_000_000.0), bars, cfg)
    assert isinstance(m_starved, PerformanceMetrics)


def test_skip_parameter_and_run():
    """M4: skip period reflected in parameters; backward-compat default 0.
    skip shifts the formation window back by `skip` bars; skip=0 == M2."""
    from decimal import Decimal
    from aurelius.backtesting.config import BacktestConfig

    strat = FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10,
                           equal_weight=True, min_price=5.0, skip=5)
    assert strat.parameters["skip"] == 5

    strat_old = FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10)
    assert strat_old.parameters["skip"] == 0  # backward-compat: contiguous

    bars = synth_bars(["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"], days=200, seed=42)
    cfg = BacktestConfig(max_drawdown_halt=Decimal("0.60"), max_position_pct=Decimal("1.0"))

    # M4 runs end-to-end (needs lookback+skip+1 bars of history to rank)
    m = run_backtest(lambda: FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10,
                                            allow_short=True, equal_weight=True,
                                            min_price=5.0, skip=5), bars, cfg)
    assert isinstance(m, PerformanceMetrics)
    assert len(m.equity_curve) > 0

    # Large skip that starves history (needs >200 bars) must not crash
    m_starved = run_backtest(
        lambda: FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10,
                               equal_weight=True, skip=300), bars, cfg)
    assert isinstance(m_starved, PerformanceMetrics)


def test_gross_vs_net_reporting():
    """M5: gross (zero-cost config) return >= net (full-cost config) return for
    the same strategy/bars. Locks the reporting invariant the M5 gross view rests
    on — costs can only subtract, so gross must dominate net. Config-only, no
    engine/strategy change."""
    from decimal import Decimal
    from aurelius.backtesting.config import BacktestConfig

    bars = synth_bars(["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"], days=200, seed=42)

    def _factory():
        return FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10,
                              allow_short=True, equal_weight=True, min_price=5.0)

    net_cfg = BacktestConfig(max_drawdown_halt=Decimal("0.60"), max_position_pct=Decimal("1.0"))
    gross_cfg = BacktestConfig(
        max_drawdown_halt=Decimal("0.60"), max_position_pct=Decimal("1.0"),
        commission_rate=Decimal("0"), spread_bps=Decimal("0"),
        slippage_impact_bps=Decimal("0"),
    )
    net = run_backtest(_factory, bars, net_cfg)
    gross = run_backtest(_factory, bars, gross_cfg)
    assert gross.total_return >= net.total_return  # costs only subtract


def test_liquidity_filter_disabled_is_identical_and_enabled_runs():
    """M7: filter OFF (default) → byte-identical baseline equity curve, and it is
    off by default. Filter ON → runs end-to-end, drops names, no crash. Locks the
    'baseline unchanged when disabled' certification requirement."""
    from decimal import Decimal
    from aurelius.backtesting.config import BacktestConfig
    from aurelius.research.liquidity import (
        DEFAULT_METRIC, LIQUIDITY_METRICS, screen,
    )

    # default OFF + params surfaced
    base = FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10)
    assert base.parameters["liquidity_filter"] is False
    assert base.parameters["liquidity_metric"] == DEFAULT_METRIC
    assert base.parameters["liquidity_pct"] == 0.0

    bars = synth_bars(list("ABCDEFGHIJ"), days=200, seed=42)
    cfg = BacktestConfig(max_drawdown_halt=Decimal("0.60"), max_position_pct=Decimal("1.0"))

    def _m4():
        return FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10,
                              allow_short=True, equal_weight=True, min_price=5.0, skip=5)

    def _m4_filter_off():  # same but explicit filter args, still disabled
        return FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10,
                              allow_short=True, equal_weight=True, min_price=5.0, skip=5,
                              liquidity_filter=False, liquidity_pct=0.20)

    m4 = run_backtest(_m4, bars, cfg)
    off = run_backtest(_m4_filter_off, bars, cfg)
    # disabled path is byte-identical to the certified baseline
    assert [str(p) for p in off.equity_curve] == [str(p) for p in m4.equity_curve]

    # enabled runs end-to-end and drops names (pct>0)
    on = run_backtest(
        lambda: FactorStrategy(lookback=30, quantile=0.20, rebalance_days=10,
                               allow_short=True, equal_weight=True, min_price=5.0, skip=5,
                               liquidity_filter=True, liquidity_pct=0.20,
                               liquidity_window=15), bars, cfg)
    assert isinstance(on, PerformanceMetrics)

    # every registered metric is callable + screen respects direction
    for name, (fn, higher) in LIQUIDITY_METRICS.items():
        val = fn([10.0] * 5, [100.0, 200, 300, 400, 500])
        assert isinstance(val, float), name
    liq = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0}
    assert screen(liq, 0.5, True) == {"C", "D"}   # keep most liquid
    assert screen(liq, 0.5, False) == {"A", "B"}  # illiquidity: keep least illiquid
    assert screen(liq, 0.0, True) == set(liq)     # disabled keeps all


def test_overlapping_factor_parameters_and_run():
    """M3: OverlappingFactorStrategy exposes K/lookback/etc; runs end-to-end.
    K=2 cohorts with short lookback so both cohorts fill within 200 synthetic bars."""
    from decimal import Decimal
    from aurelius.backtesting.config import BacktestConfig

    strat = OverlappingFactorStrategy(K=2, lookback=42, rebalance_days=21, quantile=0.20,
                                      allow_short=True, equal_weight=True, min_price=0.0)
    p = strat.parameters
    assert p["K"] == 2
    assert p["lookback"] == 42
    assert p["equal_weight"] is True
    assert p["min_price"] == 0.0

    # Defaults: K=6, lookback=126, min_price=5.0 (M2+M3 combined baseline)
    strat_default = OverlappingFactorStrategy()
    assert strat_default.parameters["K"] == 6
    assert strat_default.parameters["min_price"] == 5.0

    bars = synth_bars(["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"], days=200, seed=42)
    cfg = BacktestConfig(max_drawdown_halt=Decimal("0.60"), max_position_pct=Decimal("1.0"))

    # K=2, lookback=42: both cohorts active by trading day ~84; run should produce trades
    m = run_backtest(
        lambda: OverlappingFactorStrategy(K=2, lookback=42, rebalance_days=21,
                                          quantile=0.20, allow_short=True,
                                          equal_weight=True, min_price=0.0),
        bars, cfg,
    )
    assert isinstance(m, PerformanceMetrics)
    assert len(m.equity_curve) > 0

    # High min_price starves universe — must not crash
    m_starved = run_backtest(
        lambda: OverlappingFactorStrategy(K=2, lookback=42, rebalance_days=21,
                                          min_price=1_000_000.0),
        bars, cfg,
    )
    assert isinstance(m_starved, PerformanceMetrics)


# ── validation mechanics ──────────────────────────────────────────────────────


def test_train_test_splits_equity():
    # Single low-churn name runs to completion, so both windows are populated.
    bars = synth_bars(["AAA"], days=300)
    is_m, oos_m = train_test(lambda: MomentumStrategy(lookback=30), bars, research_config())
    # IS and OOS cover disjoint, non-empty spans of the one run
    assert is_m.equity_curve
    assert oos_m.equity_curve
    assert is_m.equity_curve[-1].timestamp < oos_m.equity_curve[0].timestamp


def test_walk_forward_returns_folds():
    bars = synth_bars(["AAA", "BBB"], days=300)
    folds = walk_forward(lambda: MomentumStrategy(lookback=20), bars, n_folds=4)
    assert 1 <= len(folds) <= 4


def test_parameter_sensitivity_reports_cv():
    bars = synth_bars(["AAA", "BBB"], days=250)
    sens = parameter_sensitivity(lambda p: MomentumStrategy(**p), {"lookback": [20, 40, 60]}, bars)
    assert len(sens.results) == 3
    assert sens.cv >= 0


# ── end-to-end: store + runner + rejection memory ─────────────────────────────


def test_investigate_records_and_updates_status():
    store = ResearchStore(":memory:")
    runner = ResearchRunner(store)
    bars = synth_bars(["AAA", "BBB", "CCC", "DDD"], days=350)
    h = runner.hypothesis("momentum persists", "trend premium", "jdoe")
    report = runner.investigate(
        hypothesis=h,
        factory_from_params=lambda p: MomentumStrategy(**p),
        base_params={"lookback": 63},
        bars=bars,
        config=research_config(),
        param_grid={"lookback": [21, 63, 126], "entry": [0.0, 0.03]},
    )
    assert report.verdict in (Verdict.ACCEPT, Verdict.REJECT, Verdict.INCONCLUSIVE)
    # experiment persisted, trial count advanced, rejected ideas queryable
    exps = store.experiments_for(h.id)
    assert len(exps) == 1
    assert store.trial_count(h.id) == 1
    if report.verdict is Verdict.REJECT:
        assert len(store.rejected_ideas()) == 1
    store.close()


def test_demo_runs_end_to_end():
    from aurelius.research import demo

    report = demo()
    assert report.verdict in (Verdict.ACCEPT, Verdict.REJECT, Verdict.INCONCLUSIVE)


def test_config_snapshot_stored_and_retrieved():
    """ExperimentRecord stores config_snapshot; find_duplicate includes config in identity."""
    from datetime import UTC, datetime

    from aurelius.research.models import ExperimentRecord, ValidationReport, Verdict

    store = ResearchStore(":memory:")
    h = store.record_hypothesis("test", "rationale", "researcher")

    def _make_rec(config_snap):
        return ExperimentRecord(
            id=__import__("uuid").uuid4().hex,
            hypothesis_id=h.id,
            researcher="researcher",
            created_at=datetime.now(UTC),
            dataset_version="abc123",
            strategy_name="momentum",
            strategy_version=1,
            features_used=["ret_1m"],
            params={"lookback": 12},
            report=ValidationReport(
                verdict=Verdict.ACCEPT,
                reasons=[],
                is_sharpe=1.5,
                oos_sharpe=1.2,
                oos_return=0.15,
                oos_max_drawdown=-0.08,
                oos_trades=40,
                n_trials=1,
                adjusted_pvalue=0.01,
            ),
            config_snapshot=config_snap,
        )

    cfg_a = {"commission_rate": "0.001", "spread_bps": "5"}
    cfg_b = {"commission_rate": "0.002", "spread_bps": "5"}  # different costs

    rec_a = _make_rec(cfg_a)
    store.record_experiment(rec_a)

    # Same config → duplicate detected
    dup = store.find_duplicate("abc123", "momentum", 1, {"lookback": 12}, cfg_a)
    assert dup == rec_a.id, "Identical run must be detected as duplicate"

    # Different config → not a duplicate
    not_dup = store.find_duplicate("abc123", "momentum", 1, {"lookback": 12}, cfg_b)
    assert not_dup is None, "Different config must NOT be detected as duplicate"

    store.close()
