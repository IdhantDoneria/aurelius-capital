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
