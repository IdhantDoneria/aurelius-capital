"""Point-in-time fundamentals store (AIDP M3).

An append-only XBRL *fact ledger*. Every fact carries the date it became known
(`filing_date` = EDGAR `filed`) and never overwrites a prior fact for the same
period. Restatements are just later rows with a newer filing_date/accession, so
"what did we know on date D" is a filter, not a special case.

This single ledger subsumes the spec's facts / shares_outstanding /
fundamental_values / restatements / filing_history tables — they are all queries
over it. `filings` holds filing-level metadata; `ingestion_log` records runs.

Additive: new store (data/fundamentals.duckdb). Nothing in M1/M2 changes.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from mentisrex.core.logging import get_logger

logger = get_logger(__name__)

_CREATE = """
CREATE TABLE IF NOT EXISTS fundamental_facts (
    cik             VARCHAR   NOT NULL,
    security_id     VARCHAR,                 -- M2 link (may be NULL until mapped)
    taxonomy        VARCHAR,                 -- us-gaap | dei | ...
    concept         VARCHAR   NOT NULL,      -- e.g. StockholdersEquity
    unit            VARCHAR   NOT NULL,      -- USD | shares | USD/shares
    period_start    DATE,                    -- NULL for instant concepts
    period_end      DATE      NOT NULL,      -- instant date / period end
    fiscal_year     INTEGER,
    fiscal_period   VARCHAR,                 -- FY | Q1..Q4
    value           DOUBLE    NOT NULL,      -- float64: fundamentals magnitudes fit; ratios divide
    form            VARCHAR,                 -- 10-K | 10-Q | 20-F | ...
    accession       VARCHAR   NOT NULL,
    filing_date     DATE      NOT NULL,      -- WHEN this value became known
    frame           VARCHAR,
    vendor          VARCHAR   DEFAULT 'sec_edgar',
    source_document VARCHAR,
    data_version    INTEGER   DEFAULT 1,
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP,
    PRIMARY KEY (cik, concept, unit, period_end, accession)
);
CREATE INDEX IF NOT EXISTS ix_facts_pit ON fundamental_facts(cik, concept, period_end, filing_date);
CREATE INDEX IF NOT EXISTS ix_facts_secid ON fundamental_facts(security_id, concept, period_end);

CREATE TABLE IF NOT EXISTS filings (
    accession           VARCHAR PRIMARY KEY,
    cik                 VARCHAR NOT NULL,
    security_id         VARCHAR,
    form                VARCHAR,
    filing_date         DATE,
    acceptance_datetime TIMESTAMP,
    period_end          DATE,
    report_type         VARCHAR,
    vendor              VARCHAR DEFAULT 'sec_edgar',
    source_document     VARCHAR,
    data_version        INTEGER DEFAULT 1,
    created_at          TIMESTAMP,
    updated_at          TIMESTAMP
);

CREATE SEQUENCE IF NOT EXISTS seq_ingestion_log START 1;
CREATE TABLE IF NOT EXISTS ingestion_log (
    id                BIGINT  DEFAULT nextval('seq_ingestion_log') PRIMARY KEY,
    cik               VARCHAR,
    ran_at            TIMESTAMP,
    facts_ingested    INTEGER,
    filings_ingested  INTEGER,
    status            VARCHAR,
    message           VARCHAR,
    vendor            VARCHAR DEFAULT 'sec_edgar',
    source_document   VARCHAR,
    data_version      INTEGER DEFAULT 1,
    created_at        TIMESTAMP,
    updated_at        TIMESTAMP
);
"""

_FACT_COLS = (
    "cik", "security_id", "taxonomy", "concept", "unit", "period_start", "period_end",
    "fiscal_year", "fiscal_period", "value", "form", "accession", "filing_date", "frame",
    "vendor", "source_document", "data_version",
)


class FundamentalsStore:
    """Append-only PIT fact ledger + filing metadata + ingestion log."""

    def __init__(self, db_path: str = "./data/fundamentals.duckdb") -> None:
        self._path = db_path
        self._in_memory = db_path == ":memory:"
        self._persistent_conn: duckdb.DuckDBPyConnection | None = None
        if not self._in_memory:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._persistent_conn = duckdb.connect(":memory:")
        with self._conn() as conn:
            conn.execute(_CREATE)

    @contextmanager
    def _conn(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        if self._in_memory and self._persistent_conn is not None:
            yield self._persistent_conn
        else:
            conn = duckdb.connect(self._path)
            try:
                yield conn
            finally:
                conn.close()

    def close(self) -> None:
        if self._persistent_conn:
            self._persistent_conn.close()
            self._persistent_conn = None

    # ── Ingest (never overwrite) ────────────────────────────────────────────────

    def write_facts(self, facts: list[dict]) -> int:
        """Append XBRL facts. INSERT OR REPLACE on the full identity PK (which
        includes accession) is idempotent per filing but never collapses distinct
        filings of the same period — that's how restatements are preserved."""
        if not facts:
            return 0
        import pandas as pd

        now = datetime.now(UTC)
        df = pd.DataFrame(
            [{**{c: f.get(c) for c in _FACT_COLS},
              "vendor": f.get("vendor", "sec_edgar"),
              "data_version": f.get("data_version", 1)} for f in facts],
            columns=list(_FACT_COLS),
        )
        df["created_at"] = now
        df["updated_at"] = now
        cols = ", ".join([*_FACT_COLS, "created_at", "updated_at"])
        with self._conn() as conn:
            conn.register("_facts_in", df)
            try:
                conn.execute(
                    f"INSERT OR REPLACE INTO fundamental_facts ({cols}) SELECT {cols} FROM _facts_in"
                )
            finally:
                conn.unregister("_facts_in")
        return len(facts)

    def record_filings(self, filings: list[dict]) -> int:
        if not filings:
            return 0
        now = datetime.now(UTC)
        with self._conn() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO filings
                (accession, cik, security_id, form, filing_date, acceptance_datetime,
                 period_end, report_type, vendor, source_document, data_version, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [[f["accession"], f["cik"], f.get("security_id"), f.get("form"),
                  f.get("filing_date"), f.get("acceptance_datetime"), f.get("period_end"),
                  f.get("report_type") or f.get("form"), f.get("vendor", "sec_edgar"),
                  f.get("source_document"), f.get("data_version", 1), now, now] for f in filings],
            )
        return len(filings)

    def log_ingestion(self, cik: str, *, facts: int, filings: int, status: str = "ok",
                      message: str = "", source_document: str | None = None) -> None:
        now = datetime.now(UTC)
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO ingestion_log
                (cik, ran_at, facts_ingested, filings_ingested, status, message,
                 source_document, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                [cik, now, facts, filings, status, message, source_document, now, now],
            )

    # ── Point-in-time query core ────────────────────────────────────────────────

    def fact_as_of(
        self, cik: str, concept: str, as_of: date, *,
        knowledge_date: date | None = None, unit: str | None = None,
        fiscal_period: str | None = None,
    ) -> dict | None:
        """The value of `concept` as it was known on `knowledge_date` (default =
        as_of), for the most recent period ended on/before `as_of`.

        PIT guarantees: period_end <= as_of (the period had ended) AND
        filing_date <= knowledge_date (it had been filed). A later restatement
        filed after knowledge_date, or any future filing, is invisible.
        """
        knowledge_date = knowledge_date or as_of
        clauses = ["cik = ?", "concept = ?", "period_end <= ?", "filing_date <= ?"]
        params: list = [cik, concept, as_of.isoformat(), knowledge_date.isoformat()]
        if unit is not None:
            clauses.append("unit = ?")
            params.append(unit)
        if fiscal_period is not None:
            clauses.append("fiscal_period = ?")
            params.append(fiscal_period)
        with self._conn() as conn:
            row = conn.execute(
                f"""SELECT value, period_end, filing_date, accession, unit, form, fiscal_period
                    FROM fundamental_facts WHERE {' AND '.join(clauses)}
                    ORDER BY period_end DESC, filing_date DESC LIMIT 1""",
                params,
            ).fetchone()
        if row is None:
            return None
        return {"value": row[0], "period_end": row[1], "filing_date": row[2],
                "accession": row[3], "unit": row[4], "form": row[5], "fiscal_period": row[6]}

    def cross_section_as_of(self, concept: str, as_of: date, *,
                            knowledge_date: date | None = None, unit: str | None = None) -> dict[str, float]:
        """{cik: value} for ALL companies as of a date — the factor-model path.
        One set-based query (latest period ≤ as_of, latest restatement filed ≤
        knowledge_date, per cik). Far faster than N point calls."""
        knowledge_date = knowledge_date or as_of
        clauses = ["concept = ?", "period_end <= ?", "filing_date <= ?"]
        params: list = [concept, as_of.isoformat(), knowledge_date.isoformat()]
        if unit is not None:
            clauses.append("unit = ?")
            params.append(unit)
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT cik, value FROM (
                        SELECT cik, value,
                               ROW_NUMBER() OVER (PARTITION BY cik ORDER BY period_end DESC, filing_date DESC) rn
                        FROM fundamental_facts WHERE {' AND '.join(clauses)}
                    ) t WHERE rn = 1""",
                params,
            ).fetchall()
        return {cik: val for cik, val in rows}

    def series_as_of(self, cik: str, concept: str, knowledge_date: date, *,
                     unit: str | None = None) -> list[dict]:
        """Full period history of a concept as known on `knowledge_date` — one
        row per period_end, taking the latest restatement filed by then."""
        clauses = ["cik = ?", "concept = ?", "filing_date <= ?"]
        params: list = [cik, concept, knowledge_date.isoformat()]
        if unit is not None:
            clauses.append("unit = ?")
            params.append(unit)
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT period_end, value, filing_date, accession FROM (
                        SELECT period_end, value, filing_date, accession,
                               ROW_NUMBER() OVER (PARTITION BY period_end ORDER BY filing_date DESC) rn
                        FROM fundamental_facts WHERE {' AND '.join(clauses)}
                    ) t WHERE rn = 1 ORDER BY period_end""",
                params,
            ).fetchall()
        return [{"period_end": r[0], "value": r[1], "filing_date": r[2], "accession": r[3]} for r in rows]
