"""Path-dependent state that must survive a process restart.

This module holds the controls that persist across programme restarts:
  - high_water_mark: the peak NAV achieved, used to compute drawdown
    (spec §10.1, §7.10: the drawdown peak is path-dependent and must survive
    a restart; a missed MOC window or a broker connection loss must not reset
    the high-water mark and disarm the drawdown circuit breakers).
  - deployment_ramp (quarters_live): the position on the 1.00x->1.75x->2.25x->2.75x
    ramp, incremented once per quarter (spec §10.2: enforced in code by reading
    persisted state; starting at the target cap means the first drawdown arrives
    before there is any live evidence to judge it against).
  - sleeve_health: per-sleeve multipliers updated daily, used by the allocator
    to de-risk sleeves with trailing Sharpe < threshold (spec §10.1 mentions
    this is path-dependent and must survive a restart).
  - halted: the halt flag, set only by risk circuit breakers when a hard limit
    fires; requires human intervention to clear (spec §10.1: a halt flattens the
    book and requires a human to type a restart command with an operator name
    and written justification, appended to an immutable audit log; there is
    deliberately no automatic path back).

Numeric values are float64, stored in JSON; locale-aware operations use UTC
with ISO-8601 format. On a process restart, StateStore.load() returns the
persisted state if valid, or a sensible fresh state if the file is missing.
A corrupt/unparseable file raises ProgrammeError, never silently resets the
high-water mark — that would disarm the drawdown breakers.

`ProgrammeState` is a MUTABLE @dataclass (not frozen), the deliberate exception
in a package where every other value is frozen. It is updated in place across
the daily run.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from mentisrex.core.logging import get_logger
from mentisrex.programme.config import ConfigError, ProgrammeError

logger = get_logger(__name__)


@dataclass
class ProgrammeState:
    """Path-dependent state that survives a restart.

    Every field is persisted atomically to state_dir/state.json on each daily
    run.

    Attributes:
        high_water_mark: Peak NAV achieved. Used to compute drawdown as the
            fraction of peak lost. Never resets on restart.
        nav: Current net asset value as of the last run.
        quarters_live: Quarters since first trade. Used to index the deployment
            ramp (spec §10.2): caps start at 1.00x and increment by one rung
            per quarter through 1.75x, 2.25x, 2.75x.
        first_trade_date: ISO-8601 date string of the first order placed, or
            None if no trade yet. Used to compute quarters_live.
        halted: True if any risk circuit breaker fired and the book was
            flattened. Requires human intervention to clear via restart().
        halt_reason: Human-readable reason for the halt, e.g. "DRAWDOWN_HALT".
            Present iff halted=True.
        sleeve_health: dict mapping sleeve name (e.g. "S1") to a scalar in
            [0.3, 1.0] or higher, used by the allocator to scale sleeve
            exposure. Sleeves with trailing Sharpe below threshold for N
            consecutive months are scaled down (spec §10.1). Empty dict means
            all sleeves at 1.0x.
        last_run_date: ISO-8601 date string of the last successful daily run,
            or None if never run.
        config_fingerprint: SHA-256 hex (first 16 chars) of the config used to
            build this state. Logged on every run to detect silent config drift.
    """

    high_water_mark: float
    nav: float
    quarters_live: int
    first_trade_date: str | None
    halted: bool
    halt_reason: str | None
    sleeve_health: dict[str, float] = field(default_factory=dict)
    last_run_date: str | None = None
    config_fingerprint: str = ""

    @property
    def drawdown(self) -> float:
        """Fraction of peak lost, in [0, 1].

        Returns 0.0 if high_water_mark <= 0 (no trades yet), else
        (high_water_mark - nav) / high_water_mark floored at 0.0.
        Positive number: 0.31 means 31% underwater.
        """
        if self.high_water_mark <= 0:
            return 0.0
        dd = (self.high_water_mark - self.nav) / self.high_water_mark
        return max(0.0, dd)


class StateStore:
    """Atomic read/write of ProgrammeState to state_dir/state.json.

    Persists all path-dependent controls (high-water mark, deployment ramp
    position, sleeve health, halt flag) so they survive a process restart or
    broker connection loss.

    load() on a missing file returns a sensible fresh state; on a corrupt file
    raises ProgrammeError (never silently resets). save() uses atomic write:
    temp file in the same directory, fsync, os.replace.

    append_audit() appends exactly one JSON line to state_dir/audit.jsonl,
    opened in append mode, flushed and fsynced. The audit log is never
    rewritten or truncated.
    """

    def __init__(self, state_dir: str) -> None:
        """Initialize the state store.

        Args:
            state_dir: Directory where state.json and audit.jsonl are stored.
                Must exist and be writable. Created by the caller if needed.
        """
        self.state_dir = Path(state_dir)
        self.state_file = self.state_dir / "state.json"
        self.audit_file = self.state_dir / "audit.jsonl"

    def load(self) -> ProgrammeState:
        """Load persisted state or return fresh defaults.

        Returns:
            Deserialised ProgrammeState from state.json if it exists and is
            valid JSON. On missing file, returns a fresh state with sensible
            defaults (high_water_mark=0.0, nav=0.0, quarters_live=0,
            first_trade_date=None, halted=False, halt_reason=None,
            sleeve_health={}, last_run_date=None, config_fingerprint="").

        Raises:
            ProgrammeError: If the file exists but is corrupt, unparseable as
                JSON, or missing required fields. A corrupt file must raise
                rather than silently reset — resetting the high_water_mark
                would disarm the drawdown circuit breakers.
        """
        if not self.state_file.exists():
            logger.info(
                "state_file_missing",
                state_file=str(self.state_file),
                action="return_fresh_state",
            )
            return ProgrammeState(
                high_water_mark=0.0,
                nav=0.0,
                quarters_live=0,
                first_trade_date=None,
                halted=False,
                halt_reason=None,
                sleeve_health={},
                last_run_date=None,
                config_fingerprint="",
            )

        try:
            with open(self.state_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            msg = f"state file corrupt or unreadable: {self.state_file}"
            logger.error("state_load_failed", state_file=str(self.state_file), error=str(e))
            raise ProgrammeError(msg, detail=str(e)) from e

        try:
            return ProgrammeState(
                high_water_mark=float(data["high_water_mark"]),
                nav=float(data["nav"]),
                quarters_live=int(data["quarters_live"]),
                first_trade_date=data.get("first_trade_date"),
                halted=bool(data["halted"]),
                halt_reason=data.get("halt_reason"),
                sleeve_health=dict(data.get("sleeve_health", {})),
                last_run_date=data.get("last_run_date"),
                config_fingerprint=str(data.get("config_fingerprint", "")),
            )
        except (KeyError, ValueError, TypeError) as e:
            msg = f"state file missing required field or invalid type: {self.state_file}"
            logger.error(
                "state_deserialize_failed",
                state_file=str(self.state_file),
                error=str(e),
            )
            raise ProgrammeError(msg, detail=str(e)) from e

    def save(self, state: ProgrammeState) -> None:
        """Atomically persist state to disk.

        Writes to a NamedTemporaryFile in the same directory as the target
        file (so it stays on the same filesystem), flushes, calls os.fsync(),
        closes, then uses os.replace() to atomically rename over the old file.
        A crash mid-write leaves the previous state readable and intact; the
        new state is never partial.

        Args:
            state: The ProgrammeState to persist.

        Raises:
            OSError: If write, fsync, or rename fails.
        """
        data = {
            "high_water_mark": state.high_water_mark,
            "nav": state.nav,
            "quarters_live": state.quarters_live,
            "first_trade_date": state.first_trade_date,
            "halted": state.halted,
            "halt_reason": state.halt_reason,
            "sleeve_health": state.sleeve_health,
            "last_run_date": state.last_run_date,
            "config_fingerprint": state.config_fingerprint,
        }

        # Ensure directory exists.
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Write to a temp file in the same directory for atomic replacement.
        try:
            fd, tmp_path = tempfile.mkstemp(dir=str(self.state_dir), text=True)
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                # Ensure temp file is cleaned up on error.
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            # Atomically replace the old file.
            os.replace(tmp_path, str(self.state_file))
            logger.info("programme_state_saved", state_file=str(self.state_file))
        except OSError as e:
            logger.error("state_save_failed", state_file=str(self.state_file), error=str(e))
            raise

    def append_audit(self, record: dict) -> None:
        """Append exactly one JSON line to the audit log.

        Opens audit.jsonl in append mode, adds ts (current UTC time, ISO-8601)
        and event keys to the record if not already present, writes one JSON
        line, flushes, fsync, closes. The audit log is append-only and is
        never rewritten or truncated.

        Args:
            record: A dict to log. Must contain "event" key (or it will be
                added). "ts" is added automatically if not present.

        Raises:
            OSError: If write or fsync fails.
        """
        # Ensure directory exists.
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Add ts and event if not present.
        ts = datetime.now(UTC).isoformat()
        if "ts" not in record:
            record["ts"] = ts
        if "event" not in record:
            record["event"] = "unknown"

        # Append one JSON line.
        try:
            with open(self.audit_file, "a") as f:
                json.dump(record, f)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            logger.info(
                "audit_record_appended",
                audit_file=str(self.audit_file),
                audit_event=record["event"],
            )
        except OSError as e:
            logger.error("audit_append_failed", audit_file=str(self.audit_file), error=str(e))
            raise

    def read_audit(self, limit: int = 100) -> list[dict]:
        """Read the last N audit records from the log.

        Args:
            limit: Maximum number of records to return (most recent first).

        Returns:
            List of audit records (dicts) in reverse chronological order
            (newest first). If the file does not exist or is empty, returns
            an empty list.
        """
        if not self.audit_file.exists():
            return []

        try:
            with open(self.audit_file) as f:
                records = [json.loads(line) for line in f if line.strip()]
            # Return most recent first.
            return list(reversed(records[-limit:]))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("audit_read_failed", audit_file=str(self.audit_file), error=str(e))
            return []


def halt(store: StateStore, reason: str) -> None:
    """Set the halt flag and persist the state.

    Sets halted=True and halt_reason to the given reason, then saves the
    state and appends an audit record. This is called by risk circuit breakers
    when a hard limit fires (spec §10.1).

    Args:
        store: The StateStore to update.
        reason: Human-readable reason for the halt, e.g. "DRAWDOWN_HALT".

    Raises:
        OSError: If save or audit append fails.
    """
    state = store.load()
    state.halted = True
    state.halt_reason = reason

    store.save(state)
    store.append_audit({"event": "halt", "reason": reason})
    logger.info("programme_halted", reason=reason)


def restart(store: StateStore, operator: str, note: str) -> None:
    """Clear the halt flag and persist the state.

    Clears halted and halt_reason, saves the state, and appends an audit
    record. Requires a non-empty operator and note; raises ConfigError if
    either is empty or whitespace-only (spec §10.1: there is deliberately no
    automatic path back from a halt).

    Args:
        store: The StateStore to update.
        operator: Name or ID of the person restarting, e.g. "ID". Must be
            non-empty and non-whitespace.
        note: Written justification for the restart. Must be non-empty and
            non-whitespace.

    Raises:
        ConfigError: If operator or note is empty or whitespace-only.
        OSError: If save or audit append fails.
    """
    if not operator or not operator.strip():
        raise ConfigError("operator must be non-empty and non-whitespace")
    if not note or not note.strip():
        raise ConfigError("note must be non-empty and non-whitespace")

    state = store.load()
    state.halted = False
    state.halt_reason = None

    store.save(state)
    store.append_audit(
        {
            "event": "restart",
            "operator": operator.strip(),
            "note": note.strip(),
        }
    )
    logger.info("programme_restarted", operator=operator.strip(), note=note.strip())
