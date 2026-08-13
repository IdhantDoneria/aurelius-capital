"""Risk limits (AIDP M13).

One frozen limit set + a pure evaluator turning a flat metrics dict into
`RiskViolation`s. Hard-limit breaches drive a REJECT; soft-limit breaches drive
APPROVE_WITH_WARNING. `None` disables a limit. This is the canonical M13 limit
model — the legacy `mentisrex.risk.RiskLimits` (Decimal, backtesting) is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass

from mentisrex.research.risk.models import RiskViolation

# metric_key -> (limit_attr, kind, severity)
_CHECKS = [
    ("max_position", "max_position", "max", "hard"),
    ("gross", "max_gross", "max", "hard"),
    ("net_abs", "max_net", "max", "hard"),
    ("leverage", "max_leverage", "max", "hard"),
    ("volatility", "max_volatility", "max", "hard"),
    ("current_drawdown_abs", "max_drawdown", "max", "hard"),
    ("var_95", "max_var_95", "max", "hard"),
    ("turnover", "max_turnover", "max", "soft"),
    ("herfindahl", "max_concentration", "max", "soft"),
    ("max_participation", "max_participation", "max", "soft"),
    ("max_days_to_liquidate", "max_days_to_liquidate", "max", "soft"),
]


@dataclass(frozen=True)
class RiskLimits:
    max_position: float | None = 0.10
    max_gross: float | None = 1.05
    max_net: float | None = 1.05
    max_leverage: float | None = 1.05
    max_volatility: float | None = None
    max_drawdown: float | None = 0.25          # absolute (fraction)
    max_var_95: float | None = None
    max_turnover: float | None = None
    max_concentration: float | None = None     # HHI cap
    max_participation: float | None = None
    max_days_to_liquidate: float | None = None

    def evaluate(self, metrics: dict) -> list[RiskViolation]:
        out: list[RiskViolation] = []
        for metric_key, attr, kind, severity in _CHECKS:
            limit = getattr(self, attr)
            if limit is None or metric_key not in metrics:
                continue
            observed = metrics[metric_key]
            if observed is None:
                continue
            breached = observed > limit if kind == "max" else observed < limit
            if breached:
                out.append(RiskViolation(limit_name=attr, observed=float(observed),
                                         limit=float(limit), kind=kind, severity=severity))
        return out
