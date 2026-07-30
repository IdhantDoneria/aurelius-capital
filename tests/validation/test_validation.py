"""Phase 14 — Statistical Validation & Robustness Framework tests.

Coverage:
  ExtendedMetrics / MetricsCalculator
  StatEngine (bootstrap, permutation, BH-FDR, Lo SE)
  RobustnessAnalyzer (regime, TC sweep, WF consistency)
  PromotionEngine (all 5 states)
  AuditRecord / capture_environment
  ComprehensiveReport (to_dict, to_markdown)
  ValidationService (data integrity, end-to-end)
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aurelius.backtesting.analytics.performance import (
    EquityPoint,
    PerformanceCalculator,
    PerformanceMetrics,
)
from aurelius.backtesting.config import BacktestConfig
from aurelius.backtesting.data.feed import BarData
from aurelius.research.runner import synth_bars
from aurelius.research.templates import MeanReversionStrategy
from aurelius.validation.audit import AuditRecord, capture_environment
from aurelius.validation.metrics import (
    MetricsCalculator,
    _excess_kurtosis,
    _percentile,
    _skewness,
)
from aurelius.validation.promotion import (
    PromotionCriteria,
    PromotionEngine,
    PromotionState,
)
from aurelius.validation.report import ComprehensiveReport
from aurelius.validation.robustness import RobustnessAnalyzer, _cost_adjusted_sharpe
from aurelius.validation.service import DataIntegrityError, ValidationService
from aurelius.validation.stats import StatEngine, _norm_ppf

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_equity_curve(returns: list[float], start: float = 1.0) -> list[EquityPoint]:
    eq = start
    t = datetime(2020, 1, 1, tzinfo=UTC)
    pts = [EquityPoint(t, eq)]
    for r in returns:
        eq *= 1 + r
        t += timedelta(days=1)
        pts.append(EquityPoint(t, eq))
    return pts


def _daily_returns(
    n: int = 252, seed: int = 1, drift: float = 0.0003, vol: float = 0.01
) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(drift, vol) for _ in range(n)]


def _flat_metrics(returns: list[float]) -> PerformanceMetrics:
    curve = _make_equity_curve(returns)
    calc = PerformanceCalculator()
    return calc.compute(curve, fills=None, initial_capital=curve[0].equity)


def _bars(n: int = 250, seed: int = 7) -> list[BarData]:
    return synth_bars(["X", "Y"], days=n, seed=seed)


# ── _percentile ───────────────────────────────────────────────────────────────


def test_percentile_basic():
    data = sorted([1.0, 2.0, 3.0, 4.0, 5.0])
    assert _percentile(data, 0.0) == pytest.approx(1.0)
    assert _percentile(data, 1.0) == pytest.approx(5.0)
    assert _percentile(data, 0.5) == pytest.approx(3.0)


def test_percentile_empty():
    assert _percentile([], 0.5) == 0.0


def test_percentile_single():
    assert _percentile([7.0], 0.5) == pytest.approx(7.0)


def test_percentile_interpolates():
    data = [0.0, 10.0]
    assert _percentile(data, 0.5) == pytest.approx(5.0)


# ── _skewness / _excess_kurtosis ─────────────────────────────────────────────


def test_skewness_symmetric():
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert abs(_skewness(data)) < 0.01  # symmetric → ~0


def test_skewness_right_tail():
    data = [1.0, 1.0, 1.0, 1.0, 10.0]
    assert _skewness(data) > 0  # right skewed


def test_skewness_left_tail():
    data = [-10.0, 1.0, 1.0, 1.0, 1.0]
    assert _skewness(data) < 0  # left skewed


def test_excess_kurtosis_normal_approx():
    rng = random.Random(42)
    data = [rng.gauss(0, 1) for _ in range(10_000)]
    assert abs(_excess_kurtosis(data)) < 0.3  # should be near 0 for large normal sample


def test_excess_kurtosis_leptokurtic():
    # single extreme outlier against near-zero mass → leptokurtic (positive excess kurtosis)
    data = [0.0] * 9 + [30.0]
    assert _excess_kurtosis(data) > 0


# ── MetricsCalculator ─────────────────────────────────────────────────────────


def test_extended_metrics_var_negative():
    returns = _daily_returns(300)
    m = _flat_metrics(returns)
    mc = MetricsCalculator()
    em = mc.compute_extended(m)
    assert em.var_95 < 0  # VaR is a loss, so negative
    assert em.var_99 <= em.var_95  # 99% VaR is worse than 95%
    assert em.cvar_95 <= em.var_95  # CVaR (tail mean) <= VaR


def test_extended_metrics_carries_base():
    returns = _daily_returns(300)
    m = _flat_metrics(returns)
    mc = MetricsCalculator()
    em = mc.compute_extended(m)
    assert em.sharpe_ratio == pytest.approx(m.sharpe_ratio)
    assert em.total_return == pytest.approx(m.total_return)


def test_extended_metrics_skew_kurtosis_finite():
    returns = _daily_returns(300)
    m = _flat_metrics(returns)
    em = MetricsCalculator().compute_extended(m)
    assert math.isfinite(em.skewness)
    assert math.isfinite(em.excess_kurtosis)


def test_extended_metrics_tail_ratio_positive():
    returns = _daily_returns(300, drift=0.001)
    m = _flat_metrics(returns)
    em = MetricsCalculator().compute_extended(m)
    assert em.tail_ratio >= 0


def test_extended_metrics_tc_drag_proportional_to_turnover():
    returns = _daily_returns(300)
    m1 = _flat_metrics(returns)
    m1.annual_turnover = 1.0
    m2 = _flat_metrics(returns)
    m2.annual_turnover = 2.0
    em1 = MetricsCalculator(commission_rate=0.001).compute_extended(m1)
    em2 = MetricsCalculator(commission_rate=0.001).compute_extended(m2)
    assert em2.tc_drag_bps == pytest.approx(2 * em1.tc_drag_bps, rel=0.01)


def test_extended_metrics_capacity_unknown_when_no_adv():
    returns = _daily_returns(300)
    m = _flat_metrics(returns)
    em = MetricsCalculator(avg_daily_volume_mm=-1.0).compute_extended(m)
    assert em.capacity_estimate_mm == -1.0


def test_extended_metrics_capacity_positive_with_adv():
    returns = _daily_returns(300, drift=0.001)
    m = _flat_metrics(returns)
    m.annual_turnover = 2.0
    em = MetricsCalculator(avg_daily_volume_mm=100.0).compute_extended(m)
    assert em.capacity_estimate_mm > 0


def test_extended_metrics_avg_drawdown_nonpositive():
    returns = _daily_returns(300)
    m = _flat_metrics(returns)
    em = MetricsCalculator().compute_extended(m)
    assert em.avg_drawdown <= 0


# ── StatEngine ────────────────────────────────────────────────────────────────


def test_bootstrap_ci_contains_observed():
    returns = _daily_returns(252, drift=0.001)
    engine = StatEngine(seed=1)
    result = engine.bootstrap_sharpe_ci(returns, n=500)
    assert result.ci_lower <= result.observed <= result.ci_upper


def test_bootstrap_ci_ordering():
    returns = _daily_returns(252, drift=0.001)
    engine = StatEngine(seed=1)
    result = engine.bootstrap_sharpe_ci(returns, n=500)
    assert result.ci_lower < result.ci_upper


def test_bootstrap_ci_flat_returns():
    returns = [0.0] * 100
    engine = StatEngine(seed=1)
    result = engine.bootstrap_sharpe_ci(returns, n=100)
    assert result.observed == pytest.approx(0.0, abs=0.01)


def test_bootstrap_ci_positive_trend():
    rng = random.Random(42)
    # Strong drift with tiny noise so Sharpe is computable (stdev > 0)
    returns = [0.003 + rng.gauss(0, 0.0005) for _ in range(252)]
    engine = StatEngine(seed=1)
    result = engine.bootstrap_sharpe_ci(returns, n=200)
    assert result.observed > 0
    assert result.ci_lower > 0  # CI should be entirely positive for strong trend


def test_permutation_pvalue_range():
    returns = _daily_returns(200, drift=0.0001)
    engine = StatEngine(seed=42)
    result = engine.permutation_pvalue(returns, n=500)
    assert 0.0 <= result.pvalue <= 1.0


def test_permutation_pvalue_high_for_noise():
    rng = random.Random(9)
    returns = [rng.gauss(0, 0.02) for _ in range(200)]  # pure noise, Sharpe ≈ 0
    engine = StatEngine(seed=42)
    result = engine.permutation_pvalue(returns, n=1000)
    assert result.pvalue > 0.10  # cannot reject H0 for noise series


def test_permutation_pvalue_low_for_strong_trend():
    rng = random.Random(7)
    # Very strong trend with noise so Sharpe is nonzero
    returns = [0.005 + rng.gauss(0, 0.001) for _ in range(200)]
    engine = StatEngine(seed=42)
    result = engine.permutation_pvalue(returns, n=1000)
    assert result.pvalue < 0.05  # permuted series almost never beats this strong a trend


def test_bonferroni_correction():
    assert StatEngine.bonferroni(0.01, 10) == pytest.approx(0.10)
    assert StatEngine.bonferroni(0.10, 5) == pytest.approx(0.50)
    assert StatEngine.bonferroni(0.5, 10) == pytest.approx(1.0)  # capped at 1


def test_bh_fdr_all_null():
    pvals = [0.5, 0.6, 0.7, 0.8, 0.9]
    _adj, rejected = StatEngine.bh_fdr(pvals, alpha=0.05)
    assert not any(rejected)


def test_bh_fdr_all_significant():
    pvals = [0.001, 0.002, 0.003]
    _adj, rejected = StatEngine.bh_fdr(pvals, alpha=0.05)
    assert all(rejected)


def test_bh_fdr_mixed():
    pvals = [0.001, 0.04, 0.50, 0.80]
    _adj, rejected = StatEngine.bh_fdr(pvals, alpha=0.05)
    assert rejected[0]  # p=0.001 should be significant
    assert not rejected[3]  # p=0.80 should not


def test_bh_fdr_empty():
    adj, rejected = StatEngine.bh_fdr([], alpha=0.05)
    assert adj == []
    assert rejected == []


def test_sharpe_se_decreases_with_n():
    sr = 1.0
    se_small = StatEngine.sharpe_se(sr, n_obs=50)
    se_large = StatEngine.sharpe_se(sr, n_obs=500)
    assert se_small > se_large


def test_norm_ppf_symmetry():
    assert _norm_ppf(0.5) == pytest.approx(0.0, abs=0.01)
    assert _norm_ppf(0.975) == pytest.approx(1.96, abs=0.02)
    assert _norm_ppf(0.025) == pytest.approx(-1.96, abs=0.02)


# ── RobustnessAnalyzer ────────────────────────────────────────────────────────


def test_cost_adjusted_sharpe_degrades():
    returns = _daily_returns(252, drift=0.001)
    rf = 0.0  # simplify
    td = 252
    sharpe_0 = _cost_adjusted_sharpe(returns, 2.0, 0, rf, td)
    sharpe_200 = _cost_adjusted_sharpe(returns, 2.0, 200, rf, td)
    assert sharpe_0 > sharpe_200


def test_robustness_assessment_structure():
    returns = _daily_returns(400, drift=0.001)
    curve = _make_equity_curve(returns)
    analyzer = RobustnessAnalyzer()
    result = analyzer.analyze(
        daily_returns=returns,
        equity_curve=curve,
        annual_turnover=2.0,
        walk_forward_sharpes=[0.8, 0.7, 0.9, 0.6],
        rolling_metric=[0.8, 0.75, 0.7],
    )
    assert isinstance(result.is_robust, bool)
    assert isinstance(result.tc_sweep.breakeven, float)
    assert result.tc_sweep.breakeven >= 0


def test_robustness_wf_inconsistency_flagged():
    returns = _daily_returns(400, drift=0.001)
    curve = _make_equity_curve(returns)
    analyzer = RobustnessAnalyzer()
    result = analyzer.analyze(
        daily_returns=returns,
        equity_curve=curve,
        annual_turnover=2.0,
        walk_forward_sharpes=[-0.5, -0.3, -0.4, -0.2],  # all negative
    )
    assert not result.walk_forward_consistent
    assert any("walk-forward" in w for w in result.weaknesses)


def test_robustness_rolling_decay_detected():
    returns = _daily_returns(400, drift=0.001)
    curve = _make_equity_curve(returns)
    analyzer = RobustnessAnalyzer()
    # Rolling metrics declining sharply
    declining = [2.0, 1.8, 1.5, 1.2, 0.8, 0.5, 0.3, 0.1, 0.0, -0.1]
    result = analyzer.analyze(
        daily_returns=returns,
        equity_curve=curve,
        annual_turnover=1.0,
        walk_forward_sharpes=[0.5],
        rolling_metric=declining,
    )
    assert not result.rolling_stable


def test_robustness_tc_sweep_length():
    returns = _daily_returns(252, drift=0.001)
    curve = _make_equity_curve(returns)
    analyzer = RobustnessAnalyzer()
    result = analyzer.analyze(returns, curve, 1.0, [0.5])
    assert len(result.tc_sweep.values) == len(result.tc_sweep.sharpes)


def test_robustness_regime_stats_present_for_long_series():
    returns = _daily_returns(600, drift=0.001)
    curve = _make_equity_curve(returns)
    analyzer = RobustnessAnalyzer(regime_window=63)
    result = analyzer.analyze(returns, curve, 1.0, [0.5])
    assert len(result.regime_stats) > 0  # enough data for regime detection


def test_robustness_regime_stats_empty_for_short_series():
    returns = _daily_returns(50, drift=0.001)
    curve = _make_equity_curve(returns)
    analyzer = RobustnessAnalyzer(regime_window=63)
    result = analyzer.analyze(returns, curve, 1.0, [0.5])
    assert result.regime_stats == []  # too short for regime window


# ── PromotionEngine ───────────────────────────────────────────────────────────


def test_promotion_requires_more_research_insufficient_obs():
    engine = PromotionEngine()
    decision = engine.decide(
        oos_sharpe=0.8,
        is_sharpe=1.2,
        adj_pvalue=0.03,
        n_oos_observations=10,  # below min
        tc_breakeven_bps=50,
        wf_consistent=True,
        regime_consistent=True,
        param_cv=0.2,
        wf_sharpes=[0.8, 0.7],
        is_robust=True,
    )
    assert decision.state == PromotionState.REQUIRES_MORE_RESEARCH


def test_promotion_rejected_negative_sharpe():
    engine = PromotionEngine()
    decision = engine.decide(
        oos_sharpe=-0.8,
        is_sharpe=1.5,
        adj_pvalue=0.80,
        n_oos_observations=100,
        tc_breakeven_bps=5,
        wf_consistent=False,
        regime_consistent=False,
        param_cv=2.0,
        wf_sharpes=[-0.8, -0.6],
        is_robust=False,
    )
    assert decision.state == PromotionState.REJECTED


def test_promotion_approved_for_paper_trading():
    engine = PromotionEngine()
    decision = engine.decide(
        oos_sharpe=0.8,
        is_sharpe=1.1,
        adj_pvalue=0.01,
        n_oos_observations=100,
        tc_breakeven_bps=80,
        wf_consistent=True,
        regime_consistent=True,
        param_cv=0.2,
        wf_sharpes=[0.7, 0.8, 0.9, 0.75],
        is_robust=True,
    )
    assert decision.state == PromotionState.APPROVED_FOR_PAPER_TRADING
    assert decision.confidence_score > 0.7


def test_promotion_approved_for_further_validation():
    engine = PromotionEngine()
    decision = engine.decide(
        oos_sharpe=0.4,
        is_sharpe=0.9,
        adj_pvalue=0.08,
        n_oos_observations=50,
        tc_breakeven_bps=40,
        wf_consistent=True,
        regime_consistent=True,
        param_cv=0.4,
        wf_sharpes=[0.4, 0.3, 0.5],
        is_robust=False,
    )
    assert decision.state == PromotionState.APPROVED_FOR_FURTHER_VALIDATION


def test_promotion_archived_regime_only():
    engine = PromotionEngine()
    decision = engine.decide(
        oos_sharpe=0.4,
        is_sharpe=0.9,
        adj_pvalue=0.07,
        n_oos_observations=60,
        tc_breakeven_bps=25,  # below paper threshold
        wf_consistent=False,
        regime_consistent=False,
        param_cv=0.5,
        wf_sharpes=[-0.2, 0.8, -0.3],
        is_robust=False,
    )
    assert decision.state == PromotionState.ARCHIVED


def test_promotion_decision_always_has_evidence():
    engine = PromotionEngine()
    for sharpe, pval, obs in [(-1.0, 0.99, 100), (0.3, 0.20, 100), (0.8, 0.01, 100)]:
        d = engine.decide(
            oos_sharpe=sharpe,
            is_sharpe=1.0,
            adj_pvalue=pval,
            n_oos_observations=obs,
            tc_breakeven_bps=30,
            wf_consistent=True,
            regime_consistent=True,
            param_cv=None,
            wf_sharpes=[],
            is_robust=True,
        )
        assert len(d.evidence) > 0
        assert len(d.next_steps) > 0


def test_promotion_confidence_score_range():
    engine = PromotionEngine()
    for sharpe in [-1.0, 0.0, 0.5, 1.0, 2.0]:
        d = engine.decide(
            oos_sharpe=sharpe,
            is_sharpe=1.0,
            adj_pvalue=0.05,
            n_oos_observations=100,
            tc_breakeven_bps=50,
            wf_consistent=True,
            regime_consistent=True,
            param_cv=0.3,
            wf_sharpes=[0.5],
            is_robust=True,
        )
        assert 0.0 <= d.confidence_score <= 1.0


def test_promotion_custom_criteria():
    strict = PromotionCriteria(min_sharpe_paper=1.5, max_adj_pvalue_paper=0.01)
    engine = PromotionEngine(strict)
    decision = engine.decide(
        oos_sharpe=0.8,
        is_sharpe=1.1,
        adj_pvalue=0.03,
        n_oos_observations=100,
        tc_breakeven_bps=80,
        wf_consistent=True,
        regime_consistent=True,
        param_cv=0.2,
        wf_sharpes=[0.8],
        is_robust=True,
    )
    # Sharpe 0.8 < strict threshold 1.5 → should not be approved for paper
    assert decision.state != PromotionState.APPROVED_FOR_PAPER_TRADING


# ── AuditRecord ───────────────────────────────────────────────────────────────


def test_audit_record_to_dict():
    record = AuditRecord(
        validated_at=datetime(2026, 7, 28, tzinfo=UTC),
        python_version="3.12.0",
        platform="Darwin",
        aurelius_commit="abc1234",
        config_hash="deadbeef01234567",
        dataset_fingerprint="fp12345678",
        random_seed=42,
        key_package_versions={"duckdb": "1.1.0"},
    )
    d = record.to_dict()
    assert d["aurelius_commit"] == "abc1234"
    assert d["random_seed"] == 42
    assert "validated_at" in d
    assert d["key_package_versions"]["duckdb"] == "1.1.0"


def test_capture_environment_returns_audit_record():
    config = BacktestConfig()
    record = capture_environment(config, "test_fingerprint")
    assert isinstance(record, AuditRecord)
    assert record.dataset_fingerprint == "test_fingerprint"
    assert record.random_seed == config.random_seed
    assert len(record.config_hash) == 16
    assert record.python_version != ""


def test_capture_environment_git_commit():
    config = BacktestConfig()
    record = capture_environment(config, "fp")
    # Should either be a real commit hash or "unknown"
    assert record.aurelius_commit != ""


def test_capture_environment_package_versions():
    config = BacktestConfig()
    record = capture_environment(config, "fp")
    assert "duckdb" in record.key_package_versions


# ── ComprehensiveReport ───────────────────────────────────────────────────────


def _make_minimal_report() -> ComprehensiveReport:
    from aurelius.validation.promotion import PromotionDecision, PromotionState
    from aurelius.validation.report import ComprehensiveReport
    from aurelius.validation.robustness import RobustnessAssessment, SensitivitySweep
    from aurelius.validation.stats import BootstrapResult, PermutationResult

    returns = _daily_returns(300, drift=0.001)
    m = _flat_metrics(returns)
    em = MetricsCalculator().compute_extended(m)

    bs = BootstrapResult(0.8, 0.5, 1.1, 0.95, 500, 0.02)
    perm = PermutationResult(0.8, 0.03, 500)
    sweep = SensitivitySweep("tc_bps", [0, 50, 100], [0.8, 0.5, 0.1], 120.0, -0.007)
    slip_sweep = SensitivitySweep("slippage_bps", [0, 30, 60], [0.8, 0.6, 0.3], 80.0, -0.01)
    robust = RobustnessAssessment(
        is_robust=True,
        regime_stats=[],
        regime_consistent=True,
        tc_sweep=sweep,
        slippage_sweep=slip_sweep,
        walk_forward_sharpes=[0.7, 0.8],
        walk_forward_cv=0.1,
        worst_fold_sharpe=0.7,
        best_fold_sharpe=0.8,
        walk_forward_consistent=True,
        rolling_stable=True,
        rolling_sharpes=[],
        weaknesses=[],
        strengths=["positive WF folds"],
    )
    promo = PromotionDecision(
        state=PromotionState.APPROVED_FOR_PAPER_TRADING,
        evidence=["OOS Sharpe: 0.800"],
        blocking_issues=[],
        confidence_score=0.75,
        next_steps=["paper trade"],
    )
    audit = AuditRecord(
        validated_at=datetime(2026, 7, 28, tzinfo=UTC),
        python_version="3.12",
        platform="Darwin",
        aurelius_commit="abc1234",
        config_hash="deadbeef01234567",
        dataset_fingerprint="fp12345678",
        random_seed=42,
        key_package_versions={"duckdb": "1.1.0"},
    )
    return ComprehensiveReport(
        experiment_id="exp-001",
        hypothesis_id="hyp-001",
        researcher="tester",
        validated_at=datetime(2026, 7, 28, tzinfo=UTC),
        metrics=em,
        sharpe_bootstrap=bs,
        permutation=perm,
        bonferroni_adj_pvalue=0.04,
        n_trials=5,
        robustness=robust,
        param_cv=0.25,
        promotion=promo,
        audit=audit,
    )


def test_report_to_dict_serializable():
    import json

    report = _make_minimal_report()
    d = report.to_dict()
    # Should be JSON-serializable
    s = json.dumps(d)
    assert '"experiment_id"' in s
    assert '"APPROVED_FOR_PAPER_TRADING"' in s.upper() or "approved_for_paper_trading" in s


def test_report_to_dict_contains_key_fields():
    report = _make_minimal_report()
    d = report.to_dict()
    assert d["experiment_id"] == "exp-001"
    assert "metrics" in d
    assert "statistical_evidence" in d
    assert "robustness" in d
    assert "promotion" in d
    assert "audit" in d


def test_report_to_markdown_is_string():
    report = _make_minimal_report()
    md = report.to_markdown()
    assert isinstance(md, str)
    assert "# Validation Report" in md
    assert "Promotion Decision" in md
    assert "Performance Metrics" in md
    assert "Statistical Evidence" in md
    assert "Robustness Assessment" in md
    assert "Audit Trail" in md


def test_report_confidence_score_property():
    report = _make_minimal_report()
    assert report.confidence_score == pytest.approx(0.75)


# ── ValidationService data integrity ─────────────────────────────────────────


def test_service_rejects_empty_bars():
    svc = ValidationService()
    with pytest.raises(DataIntegrityError, match="empty"):
        svc.validate(MeanReversionStrategy, [])


def test_service_rejects_negative_close():
    bars = _bars(50)
    bad_bar = BarData(
        symbol=bars[0].symbol,
        timestamp=bars[0].timestamp,
        open=bars[0].open,
        high=bars[0].high,
        low=bars[0].low,
        close=Decimal("-1.0"),
        volume=bars[0].volume,
    )
    svc = ValidationService()
    with pytest.raises(DataIntegrityError, match="non-positive"):
        svc.validate(MeanReversionStrategy, [bad_bar, *bars[1:]])


def test_service_rejects_high_less_than_low():
    bars = _bars(50)
    bad_bar = BarData(
        symbol=bars[0].symbol,
        timestamp=bars[0].timestamp,
        open=bars[0].open,
        high=Decimal("1.0"),
        low=Decimal("5.0"),
        close=bars[0].close,
        volume=bars[0].volume,
    )
    svc = ValidationService()
    with pytest.raises(DataIntegrityError, match="high < low"):
        svc.validate(MeanReversionStrategy, [bad_bar, *bars[1:]])


def test_service_rejects_too_few_bars():
    bars = _bars(5)
    svc = ValidationService()
    with pytest.raises(DataIntegrityError):
        svc.validate(MeanReversionStrategy, bars)


# ── ValidationService end-to-end ──────────────────────────────────────────────


@pytest.fixture
def trending_bars():
    return synth_bars(["A", "B", "C"], days=400, seed=3, drift=0.001, vol=0.008)


def test_service_returns_comprehensive_report(trending_bars):
    svc = ValidationService(n_bootstrap=100, n_permutation=100, n_wf_folds=3, seed=1)
    report = svc.validate(
        factory=MeanReversionStrategy,
        bars=trending_bars,
        experiment_id="test-001",
        hypothesis_id="hyp-001",
        researcher="tester",
    )
    assert isinstance(report, ComprehensiveReport)
    assert report.experiment_id == "test-001"
    assert report.hypothesis_id == "hyp-001"
    assert report.researcher == "tester"


def test_service_report_has_valid_promotion(trending_bars):
    svc = ValidationService(n_bootstrap=100, n_permutation=100, n_wf_folds=3, seed=1)
    report = svc.validate(MeanReversionStrategy, trending_bars)
    assert report.promotion.state in set(PromotionState)
    assert 0.0 <= report.confidence_score <= 1.0


def test_service_report_sharpe_bootstrap_has_ci(trending_bars):
    svc = ValidationService(n_bootstrap=200, n_permutation=100, n_wf_folds=2, seed=1)
    report = svc.validate(MeanReversionStrategy, trending_bars)
    bs = report.sharpe_bootstrap
    assert bs.ci_lower < bs.ci_upper
    assert bs.n_samples == 200


def test_service_report_metrics_finite(trending_bars):
    svc = ValidationService(n_bootstrap=100, n_permutation=100, n_wf_folds=2, seed=1)
    report = svc.validate(MeanReversionStrategy, trending_bars)
    m = report.metrics
    assert math.isfinite(m.sharpe_ratio)
    assert math.isfinite(m.var_95)
    assert math.isfinite(m.skewness)
    assert math.isfinite(m.excess_kurtosis)


def test_service_report_serializable(trending_bars):
    import json

    svc = ValidationService(n_bootstrap=100, n_permutation=100, n_wf_folds=2, seed=1)
    report = svc.validate(MeanReversionStrategy, trending_bars)
    d = report.to_dict()
    s = json.dumps(d)
    assert len(s) > 100


def test_service_report_markdown_nonempty(trending_bars):
    svc = ValidationService(n_bootstrap=100, n_permutation=100, n_wf_folds=2, seed=1)
    report = svc.validate(MeanReversionStrategy, trending_bars)
    md = report.to_markdown()
    assert "# Validation Report" in md
    assert report.experiment_id in md or "exp" in md


def test_service_audit_record_captured(trending_bars):
    svc = ValidationService(n_bootstrap=50, n_permutation=50, n_wf_folds=2, seed=1)
    report = svc.validate(MeanReversionStrategy, trending_bars)
    assert report.audit.random_seed == 42  # default BacktestConfig seed
    assert report.audit.dataset_fingerprint != ""
    assert report.audit.python_version != ""


def test_service_with_param_grid(trending_bars):
    def factory_from_params(p: dict) -> MeanReversionStrategy:
        return MeanReversionStrategy(**p)

    svc = ValidationService(n_bootstrap=50, n_permutation=50, n_wf_folds=2, seed=1)
    report = svc.validate(
        factory=MeanReversionStrategy,
        bars=trending_bars,
        param_grid={"lookback": [10, 20], "entry_z": [1.0, 1.5]},
        param_factory=factory_from_params,
    )
    assert report.param_cv is not None
    assert report.param_cv >= 0


def test_service_n_prior_trials_increases_adj_pvalue(trending_bars):
    svc = ValidationService(n_bootstrap=50, n_permutation=50, n_wf_folds=2, seed=1)
    r0 = svc.validate(MeanReversionStrategy, trending_bars, n_prior_trials=0)
    r100 = svc.validate(MeanReversionStrategy, trending_bars, n_prior_trials=100)
    assert r100.bonferroni_adj_pvalue >= r0.bonferroni_adj_pvalue
