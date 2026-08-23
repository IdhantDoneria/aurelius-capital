"""Deterministic synthetic fixtures for the programme's invariant suite.

Everything here is generated from a seeded RNG. The suite must run offline in
seconds: no DuckDB, no network, no market data. A test that needs real prices
to pass is not testing an invariant.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mentisrex.programme import sleeves
from mentisrex.programme.config import ProgrammeConfig, load_config
from mentisrex.programme.data import PricePanel

N_NAMES = 60
N_ROWS = 1500
BENCHMARK = "SPY"
SEED = 20260822


def _synthetic_panel(n_names: int = N_NAMES, n_rows: int = N_ROWS, seed: int = SEED) -> PricePanel:
    """Seeded geometric brownian motion with a common market factor.

    A shared factor matters: signals like residual momentum and breadth are
    defined against the benchmark, and a panel of independent random walks
    would give them nothing to work with and hide whole classes of bug.
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=n_rows, freq="C")
    names = [f"N{i:03d}" for i in range(n_names)]

    market = rng.normal(0.0004, 0.011, n_rows)
    betas = rng.uniform(0.4, 1.6, n_names)
    idio = rng.normal(0.0, 0.014, (n_rows, n_names))
    rets = market[:, None] * betas[None, :] + idio

    close = pd.DataFrame(
        100.0 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=names, dtype="float64"
    )
    close[BENCHMARK] = 300.0 * np.exp(np.cumsum(market))

    cols = [*names, BENCHMARK]
    close = close[cols]
    # Volume spread over four orders of magnitude so the liquidity screen, the
    # Amihud ratio and the liquid-half split all have something to bite on.
    base_volume = rng.uniform(2e5, 4e7, len(cols))
    noise = rng.lognormal(0.0, 0.35, (n_rows, len(cols)))
    volume = pd.DataFrame(base_volume[None, :] * noise, index=dates, columns=cols, dtype="float64")

    intraday = rng.uniform(0.002, 0.02, (n_rows, len(cols)))
    high = close * (1.0 + intraday)
    low = close * (1.0 - intraday)
    open_ = close.shift(1).bfill()

    return PricePanel(
        open=open_, high=high, low=low, close=close, volume=volume, benchmark=BENCHMARK
    )


@pytest.fixture(scope="session")
def panel() -> PricePanel:
    return _synthetic_panel()


@pytest.fixture(scope="session")
def config() -> ProgrammeConfig:
    """Defaults, but with the history requirement scaled to the fixture.

    The production `min_history_days` of 252 against a 1,500-row panel would
    leave the early sixth of the sample ineligible, which is realistic but
    wastes fixture rows. The eligibility rule itself is unchanged.
    """
    return load_config().with_overrides(
        **{
            "universe.min_dollar_volume": 1e5,
            # The production floor is 150 eligible names and the fixture panel
            # has 60. Lowering it here keeps the fixture small and fast; the
            # real threshold is exercised directly in
            # `test_quality_gate_fatals`, which drives the count to zero.
            "universe.min_eligible_names": 30,
        }
    )


@pytest.fixture(scope="session")
def mask(panel: PricePanel, config: ProgrammeConfig) -> pd.DataFrame:
    from mentisrex.programme.data import eligibility_mask

    return eligibility_mask(panel, config.universe)


@pytest.fixture(scope="session")
def built(panel: PricePanel, mask: pd.DataFrame, config: ProgrammeConfig) -> dict:
    return sleeves.build_sleeves(panel, mask, config)


@pytest.fixture(scope="session")
def policy_rates(panel: PricePanel) -> pd.Series:
    from mentisrex.programme.rates import policy_rate_path

    return policy_rate_path(panel.index)
