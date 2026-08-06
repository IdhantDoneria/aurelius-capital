"""Fundamentals quality checks (AIDP Phase 3).

Runs over the fact ledger and returns a machine-readable report. Detects the
failure modes that corrupt factor inputs: negative shares, duplicate filings,
unit/currency mismatch, missing required facts, and (informational) how many
periods carry restatements.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from aurelius.market_data.fundamentals.store import FundamentalsStore

REQUIRED_CONCEPTS = ["Assets", "Liabilities", "StockholdersEquity", "NetIncomeLoss"]


@dataclass
class QualityReport:
    cik: str
    negative_shares: int = 0
    duplicate_facts: int = 0
    unit_mismatch: dict[str, int] = field(default_factory=dict)
    restated_periods: int = 0
    missing_required: list[str] = field(default_factory=list)
    passed: bool = True

    def as_dict(self) -> dict:
        return {
            "cik": self.cik, "negative_shares": self.negative_shares,
            "duplicate_facts": self.duplicate_facts, "unit_mismatch": self.unit_mismatch,
            "restated_periods": self.restated_periods, "missing_required": self.missing_required,
            "passed": self.passed,
        }


def check(store: FundamentalsStore, cik: str, *, as_of: date | None = None) -> QualityReport:
    rep = QualityReport(cik=cik)
    with store._conn() as conn:  # noqa: SLF001 — same package
        rep.negative_shares = conn.execute(
            "SELECT COUNT(*) FROM fundamental_facts WHERE cik=? AND unit='shares' AND value < 0", [cik]
        ).fetchone()[0]
        # exact duplicate data points (same PK-ish tuple appearing >1 by value) —
        # true dup filing, not a restatement (restatement differs by accession/value)
        rep.duplicate_facts = conn.execute(
            """SELECT COALESCE(SUM(c-1),0) FROM (
                   SELECT COUNT(*) c FROM fundamental_facts WHERE cik=?
                   GROUP BY concept, unit, period_end, value HAVING COUNT(DISTINCT accession) > 1
               )""", [cik]
        ).fetchone()[0]
        # same concept+period reported in multiple units → mismatch risk
        rows = conn.execute(
            """SELECT concept, COUNT(DISTINCT unit) u FROM fundamental_facts
               WHERE cik=? GROUP BY concept, period_end HAVING u > 1""", [cik]
        ).fetchall()
        for concept, u in rows:
            rep.unit_mismatch[concept] = max(rep.unit_mismatch.get(concept, 0), u)
        rep.restated_periods = conn.execute(
            """SELECT COUNT(*) FROM (
                   SELECT concept, period_end FROM fundamental_facts WHERE cik=?
                   GROUP BY concept, period_end HAVING COUNT(DISTINCT accession) > 1
               )""", [cik]
        ).fetchone()[0]
        present = {r[0] for r in conn.execute(
            "SELECT DISTINCT concept FROM fundamental_facts WHERE cik=?", [cik]).fetchall()}
    rep.missing_required = [c for c in REQUIRED_CONCEPTS if c not in present]
    rep.passed = rep.negative_shares == 0 and not rep.unit_mismatch and not rep.missing_required
    return rep
