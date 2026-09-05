"""Per-strategy mutable runtime state (AIDP M23).

Distinct from M22's immutable StrategySpecification (the strategy *definition*)
and from M22's StrategyRegistry lifecycle state (DRAFT/DEPLOYABLE/etc).
StrategyRuntimeState is operational state: when did we last evaluate, how many
cycles have we run, is there an operational pause in effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class StrategyRuntimeState:
    """Mutable runtime state per strategy in the PaperTradingLoop.

    Not thread-safe — one loop instance owns the mutable state.
    """

    strategy_id: str
    strategy_version: str
    strategy_fingerprint: str

    last_eval_date: date | None = None
    last_snapshot_fingerprint: str = ""
    last_evaluation_id: str = ""
    last_evaluation_fingerprint: str = ""

    evaluation_count: int = 0
    error_count: int = 0
    last_error: str = ""

    # "active" | "paused"  — operational pause, distinct from M22 lifecycle state
    status: str = "active"

    def to_dict(self) -> dict:
        return {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "strategy_fingerprint": self.strategy_fingerprint,
            "last_eval_date": self.last_eval_date.isoformat() if self.last_eval_date else None,
            "last_snapshot_fingerprint": self.last_snapshot_fingerprint,
            "last_evaluation_id": self.last_evaluation_id,
            "last_evaluation_fingerprint": self.last_evaluation_fingerprint,
            "evaluation_count": self.evaluation_count,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StrategyRuntimeState:
        rs = cls(
            strategy_id=d["strategy_id"],
            strategy_version=d["strategy_version"],
            strategy_fingerprint=d["strategy_fingerprint"],
        )
        led = d.get("last_eval_date")
        rs.last_eval_date = date.fromisoformat(led) if led else None
        rs.last_snapshot_fingerprint = d.get("last_snapshot_fingerprint", "")
        rs.last_evaluation_id = d.get("last_evaluation_id", "")
        rs.last_evaluation_fingerprint = d.get("last_evaluation_fingerprint", "")
        rs.evaluation_count = d.get("evaluation_count", 0)
        rs.error_count = d.get("error_count", 0)
        rs.last_error = d.get("last_error", "")
        rs.status = d.get("status", "active")
        return rs
