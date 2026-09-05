"""Diagnostic flags (AIDP M9).

Turns the raw analysis summaries into named, severity-tagged findings that the
verdict engine and the human reader can act on. Each flag references the concrete
number that raised it — no generic messages.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Flag:
    name: str
    severity: str  # info | warning | critical
    detail: str

    def to_dict(self) -> dict:
        return {"name": self.name, "severity": self.severity, "detail": self.detail}


def _get(d, *path, default=None):
    for k in path:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def diagnose(summaries: dict, *, thresholds: dict | None = None) -> list[Flag]:
    t = {
        "max_turnover": 10.0,
        "min_wf_positive": 0.6,
        "max_swing": 0.5,
        "min_plateau": 0.5,
        "max_adv_util": 0.20,
        "max_corr_r2": 0.7,
        "max_sensitivity_disp": 0.5,
        **(thresholds or {}),
    }
    flags: list[Flag] = []

    turn = _get(summaries, "turnover", "annual_turnover", default=0.0)
    if turn > t["max_turnover"]:
        flags.append(
            Flag(
                "excess_turnover", "warning", f"annual turnover {turn:.1f}x > {t['max_turnover']}x"
            )
        )

    wf_pos = _get(summaries, "robustness", "rolling", "share_positive", default=1.0)
    if wf_pos < t["min_wf_positive"]:
        flags.append(
            Flag("unstable_alpha", "critical", f"only {wf_pos:.0%} of rolling windows positive")
        )

    swing = _get(summaries, "robustness", "leave_one_year_out", "max_swing", default=0.0)
    full = abs(_get(summaries, "robustness", "leave_one_year_out", "full", default=0.0)) or 1.0
    if swing > t["max_swing"] and swing > 0.5 * full:
        flags.append(
            Flag(
                "time_period_dependence",
                "warning",
                f"leave-one-year-out swings Sharpe by {swing:.2f}",
            )
        )

    cap = summaries.get("capacity", {})
    if (
        cap.get("capacity_signal") == "high_turnover"
        or cap.get("adv_utilisation", 0) > t["max_adv_util"]
    ):
        flags.append(
            Flag("capacity_risk", "warning", f"ADV utilisation {cap.get('adv_utilisation', 'n/a')}")
        )

    r2 = _get(summaries, "factor", "market", "r_squared", default=0.0)
    if r2 and r2 > t["max_corr_r2"]:
        flags.append(
            Flag(
                "factor_crowding",
                "warning",
                f"R² vs benchmark {r2:.2f} — returns largely explained by beta",
            )
        )

    tilt = _get(summaries, "factor", "style", "style_tilt", default=None)
    if isinstance(tilt, dict) and swing > t["max_swing"]:
        flags.append(
            Flag("style_drift", "info", "style tilt present with time-varying performance")
        )

    disp = _get(summaries, "robustness", "parameter_perturbation", "dispersion", default=0.0)
    if disp and disp > t["max_sensitivity_disp"]:
        flags.append(
            Flag(
                "parameter_fragility",
                "critical",
                f"Sharpe dispersion {disp:.2f} across neighbouring parameters",
            )
        )
    plateau = _get(summaries, "stability", "plateau_score", default=None)
    if plateau is not None and plateau < t["min_plateau"]:
        flags.append(
            Flag(
                "parameter_fragility",
                "warning",
                f"stability plateau {plateau:.0%} — isolated peak, not a plateau",
            )
        )

    return flags
