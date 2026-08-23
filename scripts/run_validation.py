"""Walk-forward, stress grid, block bootstrap, deflated Sharpe — the parts of
the research harness with no CLI subcommand (mrx backtest only runs
summary_stats). One call each, on one already-built panel.

    uv run python scripts/run_validation.py --rung recommended --db $MRX_DB
"""

from __future__ import annotations

import argparse

from mentisrex.programme import backtest, rates
from mentisrex.programme.config import load_config
from mentisrex.programme.data import build_panel

# Illustrative perturbations in the shape of specification Table 17. Edit
# these to match the exact rows you want reproduced — the harness does not
# ship a canonical list.
PERTURBATIONS = [
    {},
    {"costs.one_way_bps": 20.0},
    {"financing.borrow_fee": 0.06},
    {"universe.min_dollar_volume": 1.5e7},
    {"allocator.gross_cap": 2.00},
    {"execution.signal_to_trade_lag": 3},
]

WALK_FORWARD_SPLITS = [
    ("2017-01-01", "2018-12-31"),
    ("2019-01-01", "2020-12-31"),
    ("2021-01-01", "2022-12-31"),
    ("2023-01-01", "2024-12-31"),
    ("2025-01-01", "2026-12-31"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rung", default="recommended")
    ap.add_argument("--db", required=True)
    ap.add_argument("--start", default="2017-01-01")
    ap.add_argument("--n-paths", type=int, default=10_000)
    args = ap.parse_args()

    config = load_config().with_rung(args.rung)
    panel = build_panel(config, db_path=args.db, start=args.start)
    policy_rates = rates.policy_rate_path(panel.index)

    result = backtest.run_backtest(config, panel, policy_rates)
    print(f"── base run  ·  rung={args.rung}  ·  sharpe={result.stats['sharpe']:.4f} ──")

    print("\n── walk_forward (Table 21) ──")
    print(backtest.walk_forward(result, panel.benchmark_returns, config, WALK_FORWARD_SPLITS))

    print("\n── stress_grid (Table 17) ──")
    print(backtest.stress_grid(config, panel, PERTURBATIONS, policy_rates))

    print("\n── block_bootstrap ──")
    net = result.returns.net.dropna()
    paths = backtest.block_bootstrap(net, n_paths=args.n_paths)
    print(paths.describe())

    sharpe_std = float(paths["sharpe"].std())
    dsr = backtest.deflated_sharpe(
        observed_sharpe=result.stats["sharpe"],
        n_trials=len(PERTURBATIONS),
        n_obs=len(net),
        skew=result.stats["skew"],
        kurtosis=result.stats["excess_kurtosis"],
        sharpe_std=sharpe_std,
    )
    print(f"\n── deflated_sharpe: {dsr:.4f}  (sharpe_std={sharpe_std:.4f} from the bootstrap) ──")


if __name__ == "__main__":
    main()
