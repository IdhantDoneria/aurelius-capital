"""Temporal Security Identity Layer (AIDP M2).

CRSP/Compustat-style identity: a security is an immutable entity with a stable
surrogate `security_id`. Ticker is a mutable *attribute*, versioned over time in
`security_identity_history` with [valid_from, valid_to) intervals. The same
ticker string can belong to different securities in disjoint periods (reuse), so
ticker→security resolution is only well-defined *as of a date*.

Canonical rule: everything that needs a stable reference uses `security_id`;
ticker exists for presentation and for as-of resolution back to a security_id.

Additive: this is a new store. Legacy price/feature/backtest paths still key on
ticker; they resolve through here (see resolve_universe / resolve_as_of) without
being rewritten. See docs/AIDP_M2_IDENTITY.md.
"""

from __future__ import annotations

import hashlib
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from aurelius.core.logging import get_logger

logger = get_logger(__name__)

_FAR_FUTURE = date(9999, 12, 31)  # sentinel for an open (current) interval

_CREATE = """
CREATE TABLE IF NOT EXISTS security_master (
    security_id     VARCHAR   PRIMARY KEY,
    isin            VARCHAR,
    cusip           VARCHAR,
    figi            VARCHAR,
    sedol           VARCHAR,
    ticker          VARCHAR,               -- current (most-recent) ticker
    exchange        VARCHAR,
    country         VARCHAR,
    currency        VARCHAR,
    asset_type      VARCHAR,
    primary_listing BOOLEAN   DEFAULT TRUE,
    status          VARCHAR   DEFAULT 'active',   -- active|delisted|merged|renamed
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP
);
CREATE TABLE IF NOT EXISTS security_identity_history (
    security_id   VARCHAR NOT NULL,
    ticker        VARCHAR NOT NULL,
    exchange      VARCHAR,
    valid_from    DATE    NOT NULL,
    valid_to      DATE    NOT NULL,        -- _FAR_FUTURE = open/current
    reason        VARCHAR,
    source        VARCHAR,
    PRIMARY KEY (security_id, ticker, valid_from)
);
CREATE INDEX IF NOT EXISTS ix_hist_ticker ON security_identity_history(ticker, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS ix_hist_secid  ON security_identity_history(security_id, valid_from);
CREATE INDEX IF NOT EXISTS ix_master_isin ON security_master(isin);
CREATE INDEX IF NOT EXISTS ix_master_figi ON security_master(figi);
"""


@dataclass(frozen=True)
class Security:
    security_id: str
    ticker: str | None
    exchange: str | None
    isin: str | None = None
    cusip: str | None = None
    figi: str | None = None
    sedol: str | None = None
    country: str | None = None
    currency: str | None = None
    asset_type: str | None = None
    primary_listing: bool = True
    status: str = "active"


def make_security_id(*, isin: str | None, figi: str | None, ticker: str, exchange: str,
                     first_date: date) -> str:
    """Deterministic, idempotent per-listing surrogate id (≈ CRSP PERMNO).

    security_id identifies a *listing*, not an instrument: a dual listing has one
    ISIN but two listings, so ISIN alone must not collapse them — key on
    (ISIN, exchange). FIGI is already exchange-specific, so it stands alone.
    Fall back to (ticker, exchange, first date) — the tuple that separates a
    ticker reused decades apart. Instrument-level linkage is via shared ISIN
    (see by_isin), the PERMNO/PERMCO split.
    """
    if figi:
        natural = figi
    elif isin:
        natural = f"{isin}|{exchange.upper()}"
    else:
        natural = f"{ticker.upper()}|{exchange.upper()}|{first_date.isoformat()}"
    return "AUR" + hashlib.blake2b(natural.encode(), digest_size=7).hexdigest().upper()


class SecurityMaster:
    """DuckDB-backed temporal security identity store."""

    def __init__(self, db_path: str = "./data/identity.duckdb") -> None:
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

    # ── Registration / mutation ────────────────────────────────────────────────

    def register(self, sec: Security, *, valid_from: date, reason: str = "initial",
                 source: str = "backfill") -> str:
        """Create (or upsert) a security and open its first identity interval.

        Idempotent on security_id: re-registering the same instrument is a no-op
        for the master row and won't duplicate the opening history interval.
        """
        now = datetime.now(UTC)
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO security_master
                (security_id, isin, cusip, figi, sedol, ticker, exchange, country,
                 currency, asset_type, primary_listing, status, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,
                    COALESCE((SELECT created_at FROM security_master WHERE security_id = ?), ?), ?)""",
                [sec.security_id, sec.isin, sec.cusip, sec.figi, sec.sedol, sec.ticker,
                 sec.exchange, sec.country, sec.currency, sec.asset_type,
                 sec.primary_listing, sec.status, sec.security_id, now, now],
            )
            exists = conn.execute(
                "SELECT 1 FROM security_identity_history WHERE security_id=? AND ticker=? AND valid_from=?",
                [sec.security_id, sec.ticker, valid_from.isoformat()],
            ).fetchone()
            if not exists and sec.ticker is not None:
                conn.execute(
                    """INSERT INTO security_identity_history
                    (security_id, ticker, exchange, valid_from, valid_to, reason, source)
                    VALUES (?,?,?,?,?,?,?)""",
                    [sec.security_id, sec.ticker, sec.exchange, valid_from.isoformat(),
                     _FAR_FUTURE.isoformat(), reason, source],
                )
        return sec.security_id

    def add_identity_change(self, security_id: str, *, new_ticker: str, exchange: str | None,
                            valid_from: date, reason: str, source: str = "manual") -> None:
        """Record a ticker/exchange change: close the open interval at `valid_from`
        and open a new one. Updates the master's current ticker/exchange."""
        with self._conn() as conn:
            conn.execute(
                """UPDATE security_identity_history SET valid_to = ?
                   WHERE security_id = ? AND valid_to = ? AND valid_from <= ?""",
                [valid_from.isoformat(), security_id, _FAR_FUTURE.isoformat(), valid_from.isoformat()],
            )
            conn.execute(
                """INSERT OR REPLACE INTO security_identity_history
                (security_id, ticker, exchange, valid_from, valid_to, reason, source)
                VALUES (?,?,?,?,?,?,?)""",
                [security_id, new_ticker, exchange, valid_from.isoformat(),
                 _FAR_FUTURE.isoformat(), reason, source],
            )
            conn.execute(
                "UPDATE security_master SET ticker=?, exchange=COALESCE(?, exchange), updated_at=? WHERE security_id=?",
                [new_ticker, exchange, datetime.now(UTC), security_id],
            )

    def set_status(self, security_id: str, status: str, *, as_of: date | None = None) -> None:
        """Set lifecycle status (delisted/merged/...). If as_of given, close the
        open identity interval at that date (delisting/merger effective date)."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE security_master SET status=?, updated_at=? WHERE security_id=?",
                [status, datetime.now(UTC), security_id],
            )
            if as_of is not None:
                conn.execute(
                    "UPDATE security_identity_history SET valid_to=? WHERE security_id=? AND valid_to=?",
                    [as_of.isoformat(), security_id, _FAR_FUTURE.isoformat()],
                )

    # ── Resolution / lookup ────────────────────────────────────────────────────

    def resolve_as_of(self, ticker: str, as_of: date) -> str | None:
        """Deterministic ticker→security_id as of a date. None if the ticker was
        unassigned then. Interval [valid_from, valid_to) disambiguates reuse."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT security_id FROM security_identity_history
                   WHERE ticker = ? AND valid_from <= ? AND ? < valid_to
                   ORDER BY valid_from DESC LIMIT 1""",
                [ticker.upper(), as_of.isoformat(), as_of.isoformat()],
            ).fetchone()
            return row[0] if row else None

    def resolve_universe(self, tickers: list[str], as_of: date) -> dict[str, str]:
        """Batch resolve: {ticker: security_id} for tickers assigned on `as_of`.
        One set-based query — the efficient path for large historical universes."""
        if not tickers:
            return {}
        ups = [t.upper() for t in tickers]
        placeholders = ",".join("?" * len(ups))
        with self._conn() as conn:
            rows = conn.execute(
                f"""SELECT ticker, security_id FROM security_identity_history
                    WHERE ticker IN ({placeholders}) AND valid_from <= ? AND ? < valid_to""",
                [*ups, as_of.isoformat(), as_of.isoformat()],
            ).fetchall()
        return {t: sid for t, sid in rows}

    def live_as_of(self, as_of: date) -> list[dict]:
        """All listings live on `as_of` (valid_from ≤ as_of < valid_to). The
        survivorship-free universe primitive — a delisting closes the interval,
        so a security dead by `as_of` is absent and one not yet listed is absent,
        without any current-ticker list leaking in. Additive read (M2)."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT DISTINCT security_id, ticker, exchange
                   FROM security_identity_history
                   WHERE valid_from <= ? AND ? < valid_to
                   ORDER BY security_id""",
                [as_of.isoformat(), as_of.isoformat()],
            ).fetchall()
        return [{"security_id": r[0], "ticker": r[1], "exchange": r[2]} for r in rows]

    def all_securities(self) -> list[dict]:
        """Every security ever registered (for exclusion accounting). Additive read."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT security_id, ticker, exchange, status FROM security_master ORDER BY security_id"
            ).fetchall()
        return [{"security_id": r[0], "ticker": r[1], "exchange": r[2], "status": r[3]} for r in rows]

    def lookup_by_ticker(self, ticker: str) -> list[str]:
        """All security_ids that have *ever* used this ticker (reuse → multiple)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT security_id FROM security_identity_history WHERE ticker = ? ORDER BY security_id",
                [ticker.upper()],
            ).fetchall()
            return [r[0] for r in rows]

    def lookup_by_security_id(self, security_id: str) -> Security | None:
        with self._conn() as conn:
            r = conn.execute(
                """SELECT security_id, ticker, exchange, isin, cusip, figi, sedol,
                          country, currency, asset_type, primary_listing, status
                   FROM security_master WHERE security_id = ?""",
                [security_id],
            ).fetchone()
        if not r:
            return None
        return Security(*r)

    def current_identifier(self, security_id: str) -> str | None:
        """Current (open-interval) ticker for a security."""
        with self._conn() as conn:
            r = conn.execute(
                "SELECT ticker FROM security_identity_history WHERE security_id=? AND valid_to=? ORDER BY valid_from DESC LIMIT 1",
                [security_id, _FAR_FUTURE.isoformat()],
            ).fetchone()
            return r[0] if r else None

    def historical_identifier(self, security_id: str, as_of: date) -> str | None:
        """Ticker this security traded under on `as_of`."""
        with self._conn() as conn:
            r = conn.execute(
                """SELECT ticker FROM security_identity_history
                   WHERE security_id=? AND valid_from <= ? AND ? < valid_to
                   ORDER BY valid_from DESC LIMIT 1""",
                [security_id, as_of.isoformat(), as_of.isoformat()],
            ).fetchone()
            return r[0] if r else None

    def by_isin(self, isin: str) -> list[str]:
        """All security_ids sharing an ISIN (dual listings / share classes)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT security_id FROM security_master WHERE isin = ? ORDER BY primary_listing DESC, security_id",
                [isin],
            ).fetchall()
            return [r[0] for r in rows]
