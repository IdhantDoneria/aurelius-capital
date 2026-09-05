"""Execution diagnostics for forward validation (M24).

Analyzes M23 CycleRecord execution outcomes (orders, fills, costs, slippage).
Does NOT build a second execution model — reads data already produced by M12/M14.
"""

from __future__ import annotations

from mentisrex.research.forward_validation.models import (
    DiagnosticRecord,
    DiagnosticSeverity,
    DiscrepancyCategory,
    ValidationStatus,
    make_diagnostic,
)


def analyze_execution(cycles: list) -> dict:
    """Aggregate execution metrics from CycleRecord list.

    cycles: list of CycleRecord (or dict-like with n_orders, n_fills, reconciled)
    """
    if not cycles:
        return {
            "n_cycles": 0,
            "total_orders": 0,
            "total_fills": 0,
            "fill_rate": 0.0,
            "reconciled_rate": 0.0,
            "zero_order_cycles": 0,
            "zero_fill_cycles": 0,
            "issues": ["no cycle records"],
        }

    def _get(c, attr, default=0):
        if isinstance(c, dict):
            return c.get(attr, default)
        return getattr(c, attr, default)

    n = len(cycles)
    total_orders = sum(_get(c, "n_orders") for c in cycles)
    total_fills = sum(_get(c, "n_fills") for c in cycles)
    reconciled = sum(1 for c in cycles if _get(c, "reconciled", True))
    zero_order = sum(1 for c in cycles if _get(c, "n_orders") == 0)
    zero_fill = sum(1 for c in cycles if _get(c, "n_fills") == 0)

    fill_rate = total_fills / total_orders if total_orders > 0 else 0.0
    reconciled_rate = reconciled / n if n > 0 else 0.0

    issues = []
    if total_orders == 0:
        issues.append("no orders generated in any cycle")
    elif fill_rate < 0.5:
        issues.append(f"low fill rate: {fill_rate:.1%}")
    if reconciled_rate < 1.0:
        issues.append(f"reconciliation failures in {n - reconciled}/{n} cycles")

    return {
        "n_cycles": n,
        "total_orders": total_orders,
        "total_fills": total_fills,
        "fill_rate": fill_rate,
        "reconciled_rate": reconciled_rate,
        "zero_order_cycles": zero_order,
        "zero_fill_cycles": zero_fill,
        "issues": issues,
    }


def analyze_costs(
    spec_slippage_bps: float,
    realized_pnl_series: list[float],
    *,
    expected_cost_pct: float | None = None,
) -> dict:
    """Compare planned vs realized cost characteristics.

    realized_pnl_series: list of realized_pnl values from CycleRecords.
    expected_cost_pct: optional expected cost as fraction of capital.

    Since M23 uses MockBroker (zero cost) or SimulatedBroker (slippage_bps),
    we document the planned assumption. Realized shortfall = implementation gap.
    """
    return {
        "planned_slippage_bps": spec_slippage_bps,
        "expected_cost_pct": expected_cost_pct,
        "realized_pnl_final": realized_pnl_series[-1] if realized_pnl_series else 0.0,
        "n_observations": len(realized_pnl_series),
        "note": (
            "M23 paper trading uses SimulatedBroker or MockBroker. "
            "Cost diagnostics compare spec assumptions against broker config. "
            "Real ADV not available — partial-fill simulation is approximate."
        ),
    }


def build_execution_diagnostics(
    cycles: list,
    *,
    expected_fill_rate: float = 1.0,
    spec_slippage_bps: float = 0.0,
    fill_rate_threshold: float = 0.10,
) -> tuple[dict, list[DiagnosticRecord]]:
    """Produce execution diagnostics dict and DiagnosticRecords."""
    exec_summary = analyze_execution(cycles)
    records: list[DiagnosticRecord] = []
    n = exec_summary["n_cycles"]

    # fill rate diagnostic
    observed_fill_rate = exec_summary["fill_rate"]
    diff = abs(observed_fill_rate - expected_fill_rate)
    drifted = diff > fill_rate_threshold

    records.append(
        make_diagnostic(
            "execution.fill_rate",
            DiscrepancyCategory.EXECUTION_DRIFT,
            DiagnosticSeverity.WARNING if drifted else DiagnosticSeverity.INFO,
            "fill_rate",
            baseline=expected_fill_rate,
            observed=observed_fill_rate,
            threshold=fill_rate_threshold,
            sample_size=n,
            method="absolute_threshold",
            evidence=f"fill_rate={observed_fill_rate:.3f} expected={expected_fill_rate:.3f}",
            status=ValidationStatus.WARNING if drifted else ValidationStatus.VALID,
        )
    )

    # reconciliation diagnostic
    reconciled_rate = exec_summary["reconciled_rate"]
    if reconciled_rate < 1.0:
        records.append(
            make_diagnostic(
                "execution.reconciliation",
                DiscrepancyCategory.ACCOUNTING_DRIFT,
                DiagnosticSeverity.ERROR,
                "reconciliation_rate",
                baseline=1.0,
                observed=reconciled_rate,
                threshold=1.0,
                sample_size=n,
                method="threshold",
                evidence=f"reconciliation_rate={reconciled_rate:.3f} (expected 1.0)",
                status=ValidationStatus.FAILED,
            )
        )

    # zero-order diagnostic
    zero_order = exec_summary["zero_order_cycles"]
    if zero_order > 0:
        records.append(
            make_diagnostic(
                "execution.zero_orders",
                DiscrepancyCategory.EXECUTION_DRIFT,
                DiagnosticSeverity.INFO,
                "zero_order_cycles",
                observed=float(zero_order),
                threshold=float(n),
                sample_size=n,
                method="count",
                evidence=f"{zero_order}/{n} cycles with no orders (may be expected on non-rebalance days)",
                status=ValidationStatus.VALID,
            )
        )

    realized_pnl_series = []
    for c in cycles:
        val = c.get("realized_pnl") if isinstance(c, dict) else getattr(c, "realized_pnl", 0.0)
        realized_pnl_series.append(val)

    cost_summary = analyze_costs(spec_slippage_bps, realized_pnl_series)

    exec_summary["cost_analysis"] = cost_summary
    return exec_summary, records
