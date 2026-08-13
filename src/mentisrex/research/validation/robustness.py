"""Robustness aggregation (AIDP M9).

Combines the temporal (walk-forward), data (missing-data), and parameter
(sensitivity/stability) robustness probes into one summary the scorer consumes.
Pure composition over the individual validators.
"""

from __future__ import annotations

from mentisrex.research.validation import sensitivity, walkforward
from mentisrex.research.validation.significance import sharpe


def robustness_summary(returns, timestamps=None, *, evaluator=None, param=None,
                       param_values=None, seed: int = 0, stat_fn=sharpe) -> dict:
    out = {
        "rolling": walkforward.rolling_windows(returns, stat_fn=stat_fn),
        "expanding": walkforward.expanding_windows(returns, stat_fn=stat_fn),
        "leave_one_year_out": walkforward.leave_one_out(returns, timestamps, by="year", stat_fn=stat_fn),
        "missing_data": sensitivity.missing_data_stress(returns, stat_fn=stat_fn, seed=seed),
    }
    if evaluator is not None and param is not None and param_values:
        out["parameter_perturbation"] = sensitivity.parameter_perturbation(
            evaluator, param, param_values, stat_fn=stat_fn)
    else:
        out["parameter_perturbation"] = {"insufficient_data": True,
                                         "reason": "no evaluator/param grid"}
    return out
