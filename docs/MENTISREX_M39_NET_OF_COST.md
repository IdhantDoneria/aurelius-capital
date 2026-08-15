# M39 — Net-of-Cost Factor Evaluation

**Certification report.** P2. Wires the existing `TransactionCostModel` (AIDP M10)
into factor evaluation so long-short edges are judged **after** trading costs.
Additive; frozen `ew-momentum-exp v1.0.0` (`b69961b65bab226a500d71f45709945b`)
untouched.

## Objective (§XXI)
"A strategy must survive realistic transaction costs." Charge each factor's
long-short return the cost of its own turnover and re-test significance net.

## Implementation
- `evaluate_factor(..., cost_model=)` — reuses `research/portfolio/costs.py`
  `TransactionCostModel.linear_bps()` (commission + half-spread + slippage).
  Tracks a **two-way** per-rebalance turnover series (long + short basket
  replacement), computes per-period cost = linear_bps × two-way turnover, and
  produces `net_ls_return_series`, `net_ls_sharpe`, `net_ls_t_stat` (HAC, M31),
  `cost_bps_per_period`. No cost model → net fields stay empty (backward compatible).
- Impact term omitted here (needs per-name notionals/ADV, supplied by the backtest
  layer, not the IC panel) — documented, not silent.

## Real results (3 bps linear cost; 138 monthly rebalances × ~500 Indian equities)
| Factor | turnover | cost | gross LS Sharpe | net LS Sharpe | net HAC t | verdict |
|---|---|---|---|---|---|---|
| mom_12_1  | 0.24 | 1.5 bps/mo | 0.63 | 0.62 | **2.34** | survives |
| rev_1m    | 0.79 | 4.8 bps/mo | 0.46 | 0.42 | **1.64** | **demoted below t=2** |
| low_vol_6m| 0.23 | 1.4 bps/mo | −0.28| −0.29| −1.10 | already rejected |

**Key finding:** costs are decisive for `rev_1m` — its 0.79 monthly turnover eats
the edge and drops net HAC t from significant to **1.64**, below the promotion
bar. `mom_12_1` (0.24 turnover) is nearly cost-immune. This is exactly the
turnover-aware rejection §XXI demands: gross Sharpe alone would have kept rev_1m.

## Tests — `tests/research/test_factor_research.py` (+2, all pass)
Net-of-cost reduces Sharpe and populates the series; turnover series aligns to the
return series; no cost model → net fields NaN/empty.

## Regression
Factor/campaign/panel/ensemble suites: **29 passed.** Full research+validation
green as of M37 (2218); this milestone changes only additive net fields + turnover
definition (now two-way, one-way average preserved in `turnover`).

## Known limitations / Skipped (per CLAUDE.md)
- **Market-impact term not applied at the IC-panel level** — needs per-name order
  notionals and ADV. Unblock = run through `research/simulation` backtest with the
  full `TransactionCostModel.estimate(notionals, adv)`.
- Survivorship still uncontrolled on this panel (from M38) — deferred pending a
  delisting data source. Net-of-cost does not fix survivorship bias.
- Runner/service DoF-ledger adoption still deferred (M33).

## Next milestone
M40: survivorship reconstruction (needs delisting/corporate-action source for the
Indian panel) — quantify the survivorship haircut on these ICs; OR M33-adoption
(wire DoF ledger into runner/service). Both queued; M40 blocked on data.
