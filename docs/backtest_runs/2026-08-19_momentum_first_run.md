# Backtest Run — 2026-08-19

## Config
- **Strategy**: `cross_sectional_factor` (12-1 month momentum, long-only)
- **Script**: `scripts/run_backtest.py`
- **Period**: 2020-01-01 → 2020-02-28 (2 months only — see notes)
- **Capital**: $1,000,000
- **Universe**: US equities, Alpaca IEX bars, CIK-keyed

## Results

| Metric | Value |
|---|---|
| Total Return | -17.48% |
| CAGR (annualized) | -70.18% |
| Sharpe Ratio | -1.917 |
| Sortino Ratio | -2.503 |
| Max Drawdown | -20.16% |
| Calmar Ratio | -3.481 |
| Volatility | 54.84% |
| Trades | 682 |
| Win Rate | 36.4% |
| Profit Factor | 0.89 |
| Avg Hold Period | 15.3 days |
| Annual Turnover | 9.5x |

## Known Issues / Context

1. **Period too short**: Only ran Jan–Feb 2020, not the intended 2020–2024. DuckDB feed
   likely stopped at Feb 28 due to data boundary or script date param issue. CAGR is
   meaningless at 2 months — it's just the 2-month return annualized.

2. **COVID period**: Feb 2020 was the start of the COVID crash. S&P 500 fell ~8% in
   February alone; by late March it was down 34% from peak. A -17.48% 2-month result
   in that specific window is not clearly strategy-attributable.

3. **682 trades in 2 months**: Monthly rebalancing should produce ~50–100 trades per
   rebalance (one per symbol in long book). 682 trades implies either (a) rebalance
   triggers every bar instead of monthly, or (b) FLAT signals on every non-held symbol
   are being counted as trades. Bug in `CrossSectionalFactorStrategy` or `run_backtest.py`.

4. **9.5x annual turnover**: Consistent with trade count bug above. Expected ~1–2x for
   monthly rebalancing long-only.

## Next Steps
- Fix date range to confirm 2020–2024 run
- Debug trade count — check rebalance trigger logic in `cross_sectional.py`
- Re-run with wider period and compare to SPY benchmark
