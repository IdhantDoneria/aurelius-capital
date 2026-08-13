"""Research dashboard — prints the Part-4 panels of docs/RESEARCH_OS.md.

Read-only view over research.duckdb via ResearchStore. No new store, no new
schema: every panel is a query the ROS manual already specifies. Run on demand,
pin the output in the weekly research meeting.

Run:      python scripts/research_dashboard.py [--db ./data/research.duckdb]
Selftest: python scripts/research_dashboard.py --selftest
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from mentisrex.research.models import ExperimentRecord, ValidationReport, Verdict
from mentisrex.research.store import ResearchStore

# Lifecycle stages carried in hypotheses.status (RESEARCH_OS §3).
_BACKLOG = ("idea", "hypothesis")
_LIVE = "production"
_PAPER = "paper_trading"


def _feature_reuse_rate(store: ResearchStore) -> float | None:
    """Fraction of feature-uses that reused a feature seen in an earlier run.

    A feature-use is 'reused' if that feature name already appeared in any prior
    experiment (ordered by created_at). First appearance = new; every later use
    of the same name = reuse. High reuse means a stable feature library, not
    per-experiment sprawl.
    """
    rows = store._query(
        "SELECT features_used FROM experiments ORDER BY created_at", []
    )
    seen: set[str] = set()
    total = reused = 0
    for r in rows:
        for feat in (r["features_used"] or "").split(","):
            feat = feat.strip()
            if not feat:
                continue
            total += 1
            if feat in seen:
                reused += 1
            else:
                seen.add(feat)
    return reused / total if total else None


def panels(store: ResearchStore) -> dict:
    q = store._query

    active = {r["status"]: r["cnt"] for r in q(
        "SELECT status, COUNT(*) cnt FROM hypotheses GROUP BY status", [])}
    by_verdict = {r["verdict"]: r["cnt"] for r in q(
        "SELECT verdict, COUNT(*) cnt FROM experiments GROUP BY verdict", [])}
    completed = sum(by_verdict.values())

    decided = by_verdict.get("accept", 0) + by_verdict.get("reject", 0)
    success_rate = by_verdict.get("accept", 0) / decided if decided else None

    velocity = {str(r["wk"])[:10]: r["cnt"] for r in q(
        "SELECT date_trunc('week', created_at) wk, COUNT(*) cnt "
        "FROM experiments GROUP BY wk ORDER BY wk", [])}

    backlog = sum(active.get(s, 0) for s in _BACKLOG)

    return {
        "active_hypotheses": active,
        "completed_experiments": completed,
        "by_verdict": by_verdict,
        "success_rate": success_rate,
        "rejected_ideas": store.rejected_ideas(),
        "paper_trading": active.get(_PAPER, 0),
        "live_strategies": active.get(_LIVE, 0),
        "velocity_per_week": velocity,
        "backlog": backlog,
        "feature_reuse_rate": _feature_reuse_rate(store),
        # ponytail: compute utilization is a runs/week proxy until a compute
        # queue exists; wire real cgroup/CPU stats only when a scheduler lands.
        "compute_proxy_runs_last_week": list(velocity.values())[-1] if velocity else 0,
    }


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def render(p: dict) -> str:
    lines = ["", "=== Mentisrex Research Dashboard ===", ""]
    lines.append(f"Active hypotheses (by stage): {p['active_hypotheses'] or '{}'}")
    lines.append(f"Completed experiments:        {p['completed_experiments']}  {p['by_verdict']}")
    lines.append(f"Success rate (accept/decided): {_pct(p['success_rate'])}")
    lines.append(f"Rejected ideas (graveyard):   {len(p['rejected_ideas'])}")
    lines.append(f"In paper trading:             {p['paper_trading']}")
    lines.append(f"Live strategies:              {p['live_strategies']}")
    lines.append(f"Research backlog (unstarted): {p['backlog']}")
    lines.append(f"Feature reuse rate:           {_pct(p['feature_reuse_rate'])}")
    lines.append(f"Compute proxy (runs last wk): {p['compute_proxy_runs_last_week']}")
    lines.append("")
    lines.append("Research velocity (experiments/week):")
    for wk, n in p["velocity_per_week"].items():
        lines.append(f"  {wk}  {'#' * n} {n}")
    lines.append("")
    return "\n".join(lines)


def _selftest() -> None:
    """Seed an in-memory store and assert the panels compute correctly."""
    store = ResearchStore(":memory:")
    h = store.record_hypothesis("momentum persists", "underreaction", "alice")

    def _rec(exp_id: str, verdict: Verdict, feats: list[str]) -> ExperimentRecord:
        rep = ValidationReport(
            verdict=verdict, reasons=["selftest"], is_sharpe=1.0, oos_sharpe=0.8,
            oos_return=0.1, oos_max_drawdown=-0.05, oos_trades=40, n_trials=8,
            adjusted_pvalue=0.02,
        )
        return ExperimentRecord(
            id=exp_id, hypothesis_id=h.id, researcher="alice",
            created_at=datetime.now(UTC), dataset_version="abc123",
            strategy_name="momentum", strategy_version=1,
            features_used=feats, params={"lookback": 60}, report=rep,
        )

    store.record_experiment(_rec("e1", Verdict.ACCEPT, ["ret_60", "vol_20"]))
    store.record_experiment(_rec("e2", Verdict.REJECT, ["ret_60", "rsi_14"]))  # ret_60 reused
    store.set_hypothesis_status(h.id, "production")

    p = panels(store)
    assert p["completed_experiments"] == 2, p
    assert p["success_rate"] == 0.5, p  # 1 accept / (1 accept + 1 reject)
    assert len(p["rejected_ideas"]) == 1, p
    assert p["live_strategies"] == 1, p
    # 4 feature-uses total; ret_60's 2nd use is the only reuse -> 1/4.
    assert p["feature_reuse_rate"] == 0.25, p
    store.close()
    print("selftest ok:", render(p))


def main() -> int:
    ap = argparse.ArgumentParser(description="Mentisrex research dashboard")
    ap.add_argument("--db", default="./data/research.duckdb")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return 0

    store = ResearchStore(args.db)  # ensures tables exist even on a fresh DB
    print(render(panels(store)))
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
