"""Backtest vs paper trading comparison (M24).

Rigorous comparison of historical research/backtest metrics against forward
paper-trading results. Does NOT re-run the backtest. Consumes pre-computed
backtest_results dict provided by the caller.

backtest_results format (all optional):
  {
    "total_return": float,
    "annualized_return": float,
    "volatility": float,
    "sharpe": float,
    "max_drawdown": float,
    "fill_rate": float,
    "avg_turnover": float,
    "avg_n_signals": float,
    "slippage_bps": float,
    "universe_size": int,
    "data_source": str,
  }
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aurelius.research.forward_validation.models import (
    DiagnosticRecord,
    DiagnosticSeverity,
    DiscrepancyCategory,
    ValidationStatus,
    make_diagnostic,
)


# ── comparison table entry ────────────────────────────────────────────────────

@dataclass(frozen=True)
class ComparisonEntry:
    metric: str
    backtest: float | None
    paper: float | None
    difference: float | None
    difference_pct: float | None
    category: str
    status: str


def _entry(metric: str, backtest: float | None, paper: float | None,
           category: str = "", *, pct_threshold: float = 0.20) -> ComparisonEntry:
    diff = (paper - backtest) if (paper is not None and backtest is not None) else None
    diff_pct: float | None = None
    if diff is not None and backtest is not None and backtest != 0:
        diff_pct = diff / abs(backtest)

    status = ValidationStatus.VALID.value
    if diff_pct is not None and abs(diff_pct) > pct_threshold:
        status = ValidationStatus.WARNING.value

    return ComparisonEntry(
        metric=metric,
        backtest=backtest,
        paper=paper,
        difference=diff,
        difference_pct=diff_pct,
        category=category or "COMPARISON",
        status=status,
    )


# ── main comparison builder ───────────────────────────────────────────────────

def build_comparison(
    backtest_results: dict,
    forward_metrics: dict,
    *,
    sample_adequacy: str = "INSUFFICIENT",
) -> tuple[dict, list[DiagnosticRecord]]:
    """Compare backtest and forward metrics, producing a comparison table.

    forward_metrics should contain keys from PerformanceMetrics:
      total_return, max_drawdown, sharpe, volatility, fill_rate,
      risk_approval_rate, avg_daily_return, n_cycles, ...

    Returns (comparison_dict, list_of_DiagnosticRecord).
    """
    records: list[DiagnosticRecord] = []
    entries: list[dict] = []

    if not backtest_results:
        return {
            "compared": False,
            "reason": "no backtest results provided",
            "sample_adequacy": sample_adequacy,
            "entries": [],
        }, records

    # metrics to compare
    pairs = [
        ("total_return", "total_return", DiscrepancyCategory.EXECUTION_DRIFT, 0.30),
        ("sharpe", "sharpe", DiscrepancyCategory.SIGNAL_DRIFT, 0.50),
        ("max_drawdown", "max_drawdown", DiscrepancyCategory.PORTFOLIO_DRIFT, 0.50),
        ("volatility", "volatility", DiscrepancyCategory.STATISTICAL_NOISE, 0.30),
        ("fill_rate", "fill_rate", DiscrepancyCategory.EXECUTION_DRIFT, 0.10),
    ]

    n = forward_metrics.get("n_cycles", 0)

    for b_key, f_key, category, pct_thr in pairs:
        b_val = backtest_results.get(b_key)
        f_val = forward_metrics.get(f_key)
        if b_val is None or f_val is None:
            continue

        e = _entry(b_key, b_val, f_val, str(category), pct_threshold=pct_thr)
        entries.append({
            "metric": e.metric,
            "backtest": e.backtest,
            "paper": e.paper,
            "difference": e.difference,
            "difference_pct": e.difference_pct,
            "category": e.category,
            "status": e.status,
        })

        if e.difference_pct is not None and abs(e.difference_pct) > pct_thr:
            records.append(make_diagnostic(
                f"comparison.{b_key}",
                category,
                DiagnosticSeverity.WARNING,
                b_key,
                baseline=b_val,
                observed=f_val,
                threshold=pct_thr,
                sample_size=n,
                method="pct_threshold",
                evidence=(f"backtest={b_val:.4f} paper={f_val:.4f} "
                          f"diff={e.difference:.4f} ({e.difference_pct:.1%})"),
                status=ValidationStatus.WARNING,
            ))

    # universe-level comparison
    b_universe = backtest_results.get("universe_size")
    note = ""
    if b_universe and backtest_results.get("data_source"):
        note = (f"research used {backtest_results['data_source']} universe "
                f"({b_universe} securities). "
                "Forward paper may use different data source (M21 open/free vs institutional).")

    # explicit sample-size caveat
    adequacy_notes = {
        "INSUFFICIENT": "sample size insufficient for any statistical comparison",
        "PRELIMINARY": "preliminary sample only — treat comparisons as directional",
        "MEANINGFUL":  "meaningful sample — comparisons carry moderate weight",
        "EXTENDED":    "extended sample — comparisons are statistically informative",
    }

    return {
        "compared": True,
        "sample_adequacy": sample_adequacy,
        "n_forward_cycles": n,
        "entries": entries,
        "data_source_note": note,
        "adequacy_note": adequacy_notes.get(sample_adequacy, ""),
        "n_comparisons": len(entries),
        "n_warnings": sum(1 for e in entries if e["status"] == ValidationStatus.WARNING.value),
    }, records


def classify_discrepancies(
    data_diag: dict,
    signal_diag: dict,
    exec_diag: dict,
    portfolio_diag: dict,
    risk_diag: dict,
    comparison_diag: dict,
    all_records: list[DiagnosticRecord],
) -> list[str]:
    """Return a deduplicated list of DiscrepancyCategory values present in diagnostics."""
    categories = set()

    for rec in all_records:
        sev = rec.severity
        if sev in ("WARNING", "ERROR", "CRITICAL"):
            categories.add(rec.category)

    # always add INSUFFICIENT_SAMPLE if sample is not MEANINGFUL or EXTENDED
    adequacy = comparison_diag.get("sample_adequacy", "INSUFFICIENT")
    if adequacy in ("INSUFFICIENT", "PRELIMINARY"):
        categories.add(DiscrepancyCategory.INSUFFICIENT_SAMPLE.value)

    return sorted(categories)
