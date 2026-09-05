"""Research/deployment consistency checker (AIDP M22).

Compares a research StrategySpecification against a deployed one and reports
any configuration drift. Silent drift is the most dangerous failure mode.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mentisrex.research.strategy_deployment.models import (
    ConsistencyReport,
    StrategySpecification,
)

# Fields that constitute a material change — drift in any of these must be surfaced.
_MATERIAL_FIELDS = [
    "universe_definition",
    "signal_definition",
    "feature_definition",
    "required_data",
    "rebalance_frequency",
    "portfolio_construction_config",
    "risk_config",
    "transaction_cost_assumption",
    "slippage_assumption",
    "benchmark",
    "base_currency",
    "allowed_instruments",
    "capital_assumption",
    "model_version",
]


class ConsistencyChecker:
    """Compare research and deployed strategy specifications for drift."""

    def check(self, research: StrategySpecification,
              deployed: StrategySpecification) -> ConsistencyReport:
        drifted: list[str] = []
        differences: dict = {}

        for field in _MATERIAL_FIELDS:
            rv = getattr(research, field)
            dv = getattr(deployed, field)
            # Normalize lists before comparison (order-independent for sets-of-names)
            if isinstance(rv, list) and isinstance(dv, list):
                rv_cmp = sorted(str(x) for x in rv)
                dv_cmp = sorted(str(x) for x in dv)
            else:
                rv_cmp = rv
                dv_cmp = dv
            if rv_cmp != dv_cmp:
                drifted.append(field)
                differences[field] = {"research": rv, "deployed": dv}

        return ConsistencyReport(
            consistent=len(drifted) == 0,
            drifted_fields=drifted,
            differences=differences,
            strategy_id=deployed.strategy_id,
            checked_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
