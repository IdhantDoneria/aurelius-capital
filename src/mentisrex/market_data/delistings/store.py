"""Delisting event store (AIDP M4).

Append-only ledger of delisting events — the audit trail of *why* and *when* a
security stopped trading. M2 already models *that* a listing ended (interval
valid_to + status); this adds the richer event detail (type, reason,
last_trade_date) that the status flag can't hold, and can push the effective date
into SecurityMaster so `universe_as_of` reflects it.

Additive: new store (data/delistings.duckdb). No M1–M3 table changes.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from mentisrex.core.logging import get_logger

logger = get_logger(__name__)

# Delisting taxonomy → the lifecycle status it implies on the SecurityMaster.
DELISTING_TYPES = {
    "MERGER": "merged",
    "ACQUISITION": "merged",
    "BANKRUPTCY": "delisted",
    "LIQUIDATION": "delisted",
    "VOLUNTARY_DELIST": "delisted",
    "EXCHANGE_DELIST": "delisted",
    "UNKNOWN": "delisted",
}

_CREATE = """
CREATE SEQUENCE IF NOT EXISTS seq_delisting START 1;
CREATE TABLE IF NOT EXISTS delisting_events (
    id              BIGINT  DEFAULT nextval('seq_delisting') PRIMARY KEY,
    security_id     VARCHAR NOT NULL,
    event_date      DATE,                    -- when the event was announced/known
    effective_date  DATE    NOT NULL,        -- when the listing actually ended
    delisting_type  VARCHAR NOT NULL,
    reason          VARCHAR,
    last_trade_date DATE,
    exchange        VARCHAR,
    source          VARCHAR,
    vendor          VARCHAR,
    data_version    INTEGER DEFAULT 1,
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_delist_secid ON delisting_events(security_id, effective_date);
"""


@dataclass(frozen=True)
class DelistingEvent:
    security_id: str
    effective_date: date
    delisting_type: str = "UNKNOWN"
    event_date: date | None = None
    reason: str | None = None
    last_trade_date: date | None = None
    exchange: str | None = None
    source: str | None = None
    vendor: str | None = None
    data_version: int = 1


class DelistingStore:
    def __init__(self, db_path: str = "./data/delistings.duckdb") -> None:
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

    def record(self, ev: DelistingEvent) -> None:
        """Append a delisting event. Never overwrites — every record is kept."""
        if ev.delisting_type not in DELISTING_TYPES:
            raise ValueError(f"unknown delisting_type {ev.delisting_type!r}")
        now = datetime.now(UTC)
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO delisting_events
                (security_id, event_date, effective_date, delisting_type, reason,
                 last_trade_date, exchange, source, vendor, data_version, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    ev.security_id,
                    ev.event_date,
                    ev.effective_date,
                    ev.delisting_type,
                    ev.reason,
                    ev.last_trade_date,
                    ev.exchange,
                    ev.source,
                    ev.vendor,
                    ev.data_version,
                    now,
                    now,
                ],
            )

    def events_for(self, security_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT security_id, event_date, effective_date, delisting_type, reason,
                          last_trade_date, exchange, source, vendor
                   FROM delisting_events WHERE security_id = ? ORDER BY effective_date""",
                [security_id],
            ).fetchall()
        keys = (
            "security_id",
            "event_date",
            "effective_date",
            "delisting_type",
            "reason",
            "last_trade_date",
            "exchange",
            "source",
            "vendor",
        )
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def apply_to_master(self, security_master) -> int:
        """Push each security's earliest delisting into SecurityMaster: set status
        and close the open identity interval at the effective date. Idempotent —
        M2 set_status only closes the still-open interval. This is how a
        delisting removes a security from `universe_as_of` after its date."""
        applied = 0
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT security_id, delisting_type, MIN(effective_date)
                   FROM delisting_events GROUP BY security_id, delisting_type"""
            ).fetchall()
        # earliest effective per security wins the interval close
        earliest: dict[str, tuple[date, str]] = {}
        for sid, dtype, eff in rows:
            eff = eff if isinstance(eff, date) else date.fromisoformat(str(eff))
            if sid not in earliest or eff < earliest[sid][0]:
                earliest[sid] = (eff, DELISTING_TYPES[dtype])
        for sid, (eff, status) in earliest.items():
            security_master.set_status(sid, status, as_of=eff)
            applied += 1
        return applied
