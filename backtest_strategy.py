#!/usr/bin/env python
"""
Backtest the Mentisrex Programme v3.0 strategy across available historical data.

Usage:
    python backtest_strategy.py
    python backtest_strategy.py --rung recommended --db data/analytics.duckdb
    python backtest_strategy.py --rung deploy --start 2020-01-01

Options:
    --rung {deploy,conservative,mandate,standard,recommended,aggressive}
        Deployment configuration rung. Default: recommended
    --db PATH
        Path to analytics.duckdb. Default: data/analytics.duckdb
    --start DATE
        Backtest start date (YYYY-MM-DD). Default: 2017-01-01
    --end DATE
        Backtest end date (YYYY-MM-DD). Default: today
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from mentisrex.programme import backtest, rates
from mentisrex.programme.config import load_config
from mentisrex.programme.data import build_panel


def _format_stat(value: float, decimals: int = 4) -> str:
    """Format a numeric statistic for display."""
    if isinstance(value, (int, float)):
        return f"{value:.{decimals}f}"
    return str(value)


def _print_results(result: backtest.BacktestResult, rung: str) -> None:
    """Pretty-print backtest results."""
    print("\n" + "=" * 80)
    print(f"BACKTEST COMPLETE  ·  rung={rung}  ·  fingerprint={result.config_fingerprint}")
    print("=" * 80 + "\n")

    stats = result.stats
    n_days = stats.get('n_days', 0)
    key_metrics = [
        ("Years", f"{n_days / 252:.2f}"),
        ("CAGR", f"{stats['cagr']:.4f}"),
        ("Volatility", f"{stats['vol']:.4f}"),
        ("Sharpe Ratio", f"{stats['sharpe']:.4f}"),
        ("Sortino Ratio", f"{stats['sortino']:.4f}"),
        ("Max Drawdown", f"{stats['max_drawdown']:.4f}"),
        ("Calmar Ratio", f"{stats['calmar']:.4f}"),
        ("Hit Rate", f"{stats['hit_rate']:.4f}"),
        ("Avg Gross Exposure", f"{stats['avg_gross']:.4f}"),
        ("Annual Turnover", f"{stats['turnover_annual']:.4f}"),
        ("Terminal Value of $1M", f"${stats['terminal_value_of_1m']:,.0f}"),
    ]

    print("KEY METRICS")
    print("-" * 80)
    for label, value in key_metrics:
        print(f"  {label:<30} {value:>20}")

    print("\nRISK METRICS")
    print("-" * 80)
    risk_metrics = [
        ("Beta", f"{stats['beta']:.4f}"),
        ("Downside Beta", f"{stats['downside_beta']:.4f}"),
        ("Alpha", f"{stats['alpha']:.4f}"),
        ("Correlation", f"{stats['correlation']:.4f}"),
        ("Skew", f"{stats['skew']:.4f}"),
        ("Excess Kurtosis", f"{stats['excess_kurtosis']:.4f}"),
        ("Best Day", f"{stats['best_day']:.4f}"),
        ("Worst Day", f"{stats['worst_day']:.4f}"),
        ("Worst 12-Month Return", f"{stats['worst_12m']:.4f}"),
        ("VaR (95%)", f"{stats['var_95']:.4f}"),
        ("CVaR (95%)", f"{stats['cvar_95']:.4f}"),
        ("VaR (99%)", f"{stats['var_99']:.4f}"),
        ("CVaR (99%)", f"{stats['cvar_99']:.4f}"),
    ]
    for label, value in risk_metrics:
        print(f"  {label:<30} {value:>20}")

    print("\nCOST METRICS")
    print("-" * 80)
    cost_metrics = [
        ("Cost Drag (annual)", f"{stats['cost_drag']:.4f}"),
        ("Financing Drag (annual)", f"{stats['financing_drag']:.4f}"),
        ("Days Below High-Water Mark", f"{stats['days_below_hwm']:.2%}"),
        ("Longest Underwater Period (days)", f"{int(stats['longest_underwater_days'])}"),
    ]
    for label, value in cost_metrics:
        print(f"  {label:<30} {value:>20}")

    print("\n" + "=" * 80)
    print("Backtested means hypothetical: simulated results on a survivorship-biased")
    print("sample, produced with full knowledge of what happened in the period.")
    print("=" * 80 + "\n")


def main() -> int:
    """Run backtest."""
    parser = argparse.ArgumentParser(
        description="Backtest the Mentisrex Programme v3.0 strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--rung",
        choices=["deploy", "conservative", "mandate", "standard", "recommended", "aggressive"],
        default="recommended",
        help="Deployment rung (default: recommended)",
    )
    parser.add_argument(
        "--db",
        default="data/analytics.duckdb",
        help="Path to analytics.duckdb (default: data/analytics.duckdb)",
    )
    parser.add_argument(
        "--start",
        default="2017-01-01",
        help="Backtest start date YYYY-MM-DD (default: 2017-01-01)",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="Backtest end date YYYY-MM-DD (default: latest available)",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}", file=sys.stderr)
        return 1

    try:
        print(f"\n► Loading configuration (rung={args.rung})...")
        config = load_config().with_rung(args.rung)

        print(f"► Building price panel (start={args.start}, end={args.end or 'latest'})...")
        panel = build_panel(
            config,
            db_path=str(db_path),
            start=args.start,
            end=args.end,
        )
        n_dates = len(panel.index)
        print(f"  · {n_dates} trading days")
        print(f"  · Period: {panel.index[0].date()} to {panel.index[-1].date()}")

        print("► Loading policy rates...")
        policy_rates = rates.policy_rate_path(panel.index)

        print("► Running backtest...")
        result = backtest.run_backtest(config, panel, policy_rates)

        _print_results(result, args.rung)
        return 0

    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
