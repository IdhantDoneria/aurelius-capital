"""Research matrix quality checks (AIDP M6).

Structural integrity only — PIT correctness is enforced upstream by each source's
`*_as_of` gate, so there's nothing to re-verify here. Missing features are legal
(a security may lack fundamentals); this reports them without failing.
"""

from __future__ import annotations

from mentisrex.market_data.research_matrix.schema import ResearchMatrix


def check(matrix: ResearchMatrix) -> dict:
    df = matrix.frame
    dup = bool(df.index.duplicated().any())
    all_null = [c for c in df.columns if df[c].isna().all()]
    return {
        "rows": len(df),
        "columns": list(df.columns),
        "duplicate_ids": dup,
        "all_null_columns": all_null,  # informational — missing data, not corruption
        "ok": not dup,
    }
