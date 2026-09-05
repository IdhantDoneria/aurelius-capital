"""Production dataset isolation (G2).

The production research store (``PRODUCTION_DB``) must contain only validated
institutional data. Toy / sample loaders must never write into it, and
institutional reproductions must read only validated series (not truncated
synthetic residue left by past toy runs).

Two enforced guarantees:

* :func:`assert_not_production` — a toy/sample loader calls this with its target
  DB path; it raises if the path resolves to the production database, so toy
  data physically cannot be written there.
* :func:`validated_universe_filter` — a SQL predicate that admits only series
  with enough history to be plausibly real, so residual toy rows cannot enter a
  reproduction universe.
"""

from __future__ import annotations

from pathlib import Path

PRODUCTION_DB = "./data/analytics.duckdb"
TOY_DB = "./data/toy.duckdb"

# Evidence-based gate (G2, reopened). Measured on production analytics.duckdb:
#   known toy contamination : max 520 bars (synthetic 2022-2023 window)
#   legitimate production    : min 2201 bars (US+India), median ~3162
# 521 is the minimum threshold that rejects every known 520-bar toy series while
# admitting all real data. The 521..2201 gap is wide, so 521 also stays maximally
# permissive toward legitimate short-history listings.
MIN_VALIDATED_BARS = 521


class ProductionIsolationError(RuntimeError):
    """Raised when a toy/sample loader targets the production database."""


def _resolve(path: str) -> Path:
    return Path(path).expanduser().resolve()


def assert_not_production(db_path: str) -> None:
    """Raise if ``db_path`` is the production database. Call before any toy write."""
    if _resolve(db_path) == _resolve(PRODUCTION_DB):
        raise ProductionIsolationError(
            f"toy/sample loader may not write to the production database "
            f"({PRODUCTION_DB}); use an isolated store such as {TOY_DB}"
        )


def validated_universe_filter(base_predicate: str = "frequency='1d'") -> str:
    """SQL WHERE clause admitting only symbols with >= MIN_VALIDATED_BARS bars.

    Use in reproduction load queries so truncated toy series are excluded on a
    principled data-quality basis rather than a hardcoded ticker blacklist.
    """
    return (
        f"{base_predicate} AND symbol IN ("
        f"SELECT symbol FROM ohlcv WHERE {base_predicate} "
        f"GROUP BY symbol HAVING COUNT(*) >= {MIN_VALIDATED_BARS})"
    )
