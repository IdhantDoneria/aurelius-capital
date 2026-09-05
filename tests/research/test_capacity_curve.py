"""M40: capacity engine — net Sharpe decays with AUM via √-law impact."""

import numpy as np

from mentisrex.research.capacity_curve import capacity_curve
from mentisrex.research.portfolio.costs import TransactionCostModel


def _panels(T, N, edge, adv_level, seed=0):
    rng = np.random.default_rng(seed)
    signals, fwd, adv = [], [], []
    for _ in range(T):
        names = [f"s{i}" for i in range(N)]
        s = rng.standard_normal(N)
        signals.append(dict(zip(names, s, strict=False)))
        fwd.append(dict(zip(names, edge * s + rng.standard_normal(N) * 0.05, strict=False)))
        adv.append(dict.fromkeys(names, adv_level))
    return signals, fwd, adv


def test_sharpe_decays_with_aum():
    sig, fwd, adv = _panels(80, 50, edge=0.02, adv_level=1e6)
    cm = TransactionCostModel(impact_coef=0.1)
    r = capacity_curve(sig, fwd, adv, cost_model=cm, aum_levels=[1e6, 1e7, 1e8, 1e9])
    sharpes = [p["net_sharpe"] for p in r["curve"]]
    # monotone non-increasing as AUM grows (impact only hurts)
    assert all(sharpes[i] >= sharpes[i + 1] - 1e-9 for i in range(len(sharpes) - 1))


def test_higher_adv_gives_more_capacity():
    cm = TransactionCostModel(impact_coef=0.1)
    lo = capacity_curve(*_panels(80, 50, 0.02, 1e5), cost_model=cm, aum_levels=[1e7, 1e8])
    hi = capacity_curve(*_panels(80, 50, 0.02, 1e8), cost_model=cm, aum_levels=[1e7, 1e8])
    # deeper ADV => higher net Sharpe at the same AUM
    assert hi["curve"][-1]["net_sharpe"] >= lo["curve"][-1]["net_sharpe"]


def test_half_capacity_detected():
    sig, fwd, adv = _panels(80, 50, edge=0.02, adv_level=5e5)
    cm = TransactionCostModel(impact_coef=0.2)
    r = capacity_curve(sig, fwd, adv, cost_model=cm, aum_levels=[1e6, 1e7, 5e7, 1e8, 5e8, 1e9, 5e9])
    if r["base_sharpe"] > 0:
        assert r["half_sharpe_capacity_usd"] is not None
