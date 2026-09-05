"""M33: research degrees-of-freedom ledger + DSR feed."""

import pytest

from mentisrex.research.dof_ledger import DoFLedger, Trial
from mentisrex.research.validation.overfitting import deflated_sharpe_ratio


@pytest.fixture
def ledger():
    lg = DoFLedger(":memory:")
    yield lg
    lg.close()


def test_record_and_effective_trials(ledger):
    for i in range(3):
        assert ledger.record(Trial(family="momentum", hypothesis_id=f"h{i}"))
    assert ledger.effective_trials("momentum") == 3


def test_dedup_identical_trial(ledger):
    t = Trial(
        family="value",
        hypothesis_id="h1",
        variant="ep",
        dataset_id="d1",
        period="2000-2010",
        params={"lookback": 12},
    )
    assert ledger.record(t) is True
    assert ledger.record(t) is False  # identical fingerprint -> not counted
    assert ledger.effective_trials("value") == 1


def test_params_differentiate_trials(ledger):
    ledger.record(Trial(family="mom", hypothesis_id="h1", params={"lb": 6}))
    ledger.record(Trial(family="mom", hypothesis_id="h1", params={"lb": 12}))
    assert ledger.effective_trials("mom") == 2


def test_cross_hypothesis_snooping_is_counted(ledger):
    # same mechanism ("momentum"), 50 different hypothesis ids => 50 DoF, not ~1
    for i in range(50):
        ledger.record(Trial(family="momentum", hypothesis_id=f"h{i}", variant=f"v{i}"))
    assert ledger.effective_trials("momentum") == 50


def test_breakdown_axis_counts(ledger):
    ledger.record(
        Trial(
            family="q",
            hypothesis_id="h1",
            variant="a",
            dataset_id="us",
            period="p1",
            params={"x": 1},
        )
    )
    ledger.record(
        Trial(
            family="q",
            hypothesis_id="h2",
            variant="b",
            dataset_id="eu",
            period="p2",
            params={"x": 2},
        )
    )
    b = ledger.breakdown("q")
    assert b == {
        "hypotheses": 2,
        "variants": 2,
        "datasets": 2,
        "periods": 2,
        "parameter_sets": 2,
        "trials": 2,
    }


def test_families_listing(ledger):
    ledger.record(Trial(family="b"))
    ledger.record(Trial(family="a"))
    assert ledger.families() == ["a", "b"]


def test_n_trials_for_feeds_dsr(ledger):
    for i in range(9):
        ledger.record(Trial(family="mom", hypothesis_id=f"h{i}"))
    n = ledger.n_trials_for("mom", grid_size=1)  # 9 prior + 1 = 10
    assert n == 10
    # more trials => higher expected-max Sharpe bar => lower/discounted DSR
    returns = [0.01, -0.005, 0.012, 0.002, -0.001, 0.008] * 40
    dsr_low = deflated_sharpe_ratio(returns, n_trials=1)["dsr"]
    dsr_high_n = deflated_sharpe_ratio(returns, n_trials=n)["dsr"]
    assert dsr_high_n <= dsr_low


def test_unknown_family_zero(ledger):
    assert ledger.effective_trials("nope") == 0
    assert ledger.n_trials_for("nope") == 1
