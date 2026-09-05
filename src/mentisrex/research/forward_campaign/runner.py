"""Forward operations runner (M26).

ForwardOperationsRunner is the operational orchestration layer above ForwardCampaign.
It adds:
  - check_and_run(as_of): single cron-safe check-and-execute call
  - run_months(dates, records): multi-month simulation for tests
  - operational_status(): enriched monitoring dict with next_expected_cycle

Stateless between process restarts — all durable state lives in the campaign
checkpoint and sealed cycle files. Session metrics reset on each process start.

Usage:
    runner = ForwardOperationsRunner(spec, logic, campaign_dir, universe, capital)
    result = runner.check_and_run()           # cron call
    results = runner.run_months(date_list)    # operational simulation
    status = runner.operational_status()      # monitoring
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from mentisrex.research.forward_campaign.campaign import CycleResult, ForwardCampaign
from mentisrex.research.forward_campaign.record import CycleStatus
from mentisrex.research.paper_trading.scheduler import RebalanceScheduler


@dataclass
class RunnerConfig:
    """Operational configuration for ForwardOperationsRunner."""

    log_prefix: str = "[forward-runner]"


class _LastEvalStub:
    """Minimal duck-type stub for RebalanceScheduler.next_due()."""

    def __init__(self, last_eval_date: date) -> None:
        self.last_eval_date = last_eval_date


class ForwardOperationsRunner:
    """Operational wrapper around ForwardCampaign.

    Adds session-level state tracking (run counts, errors) and computes
    next_expected_cycle for monitoring dashboards. All durable state is in
    the campaign directory — this class is safe to re-create each call.

    Design: check-and-run, not daemon. Call from cron or a scheduler process.
    The idempotency guarantee from M25 means multiple cron firings per month
    are safe: all after the first return ALREADY_SEALED.
    """

    def __init__(
        self,
        spec,
        logic,
        campaign_dir: str | Path,
        universe: list,
        starting_capital: float,
        campaign_id: str = "",
        *,
        config: RunnerConfig | None = None,
    ) -> None:
        self._spec = spec
        self._logic = logic
        self._campaign_dir = Path(campaign_dir)
        self._universe = list(universe)
        self._starting_capital = starting_capital
        self._campaign_id = campaign_id
        self._config = config or RunnerConfig()
        self._scheduler = RebalanceScheduler()
        # session-only state — resets on restart (durable state is in campaign dir)
        self._run_count: int = 0
        self._session_successes: int = 0
        self._session_failures: int = 0
        self._last_status: str = ""
        self._last_error: str = ""
        self._last_run_at: str = ""

    # ── public API ─────────────────────────────────────────────────────────────

    def check_and_run(
        self, as_of: date | None = None, *, provider_records: list | None = None
    ) -> CycleResult:
        """Check if a forward cycle is due for as_of and execute it.

        Idempotent: repeated calls for the same month return ALREADY_SEALED.
        Safe to call from cron — no duplicates even if cron fires multiple times.

        Args:
            as_of: Observation date. Defaults to today.
            provider_records: Optional offline provider fixture (tests only).
                              If None, real Yahoo Finance data is fetched.

        Returns:
            CycleResult with status SUCCESS | SKIPPED | FAILED | ALREADY_SEALED.
        """
        as_of = as_of or date.today()
        campaign = self._get_campaign()
        result = campaign.run(as_of, provider_records=provider_records)

        # update session state
        self._run_count += 1
        self._last_status = result.status
        self._last_run_at = datetime.now(UTC).replace(tzinfo=None).isoformat()

        if result.status == CycleStatus.SUCCESS:
            self._session_successes += 1
            self._last_error = ""
        elif result.status == CycleStatus.FAILED:
            self._session_failures += 1
            self._last_error = result.record.error_message if result.record else result.message

        return result

    def run_months(
        self, month_dates: list[date], provider_records_list: list | None = None
    ) -> list[CycleResult]:
        """Execute check_and_run for each date in month_dates.

        OPERATIONAL SIMULATION — not genuine forward evidence.
        Deterministically exercises multiple monthly cycles without network calls
        when provider_records_list is supplied.

        Args:
            month_dates: Sequence of as_of dates (one per intended cycle).
            provider_records_list: Optional parallel list of provider record
                                   fixtures; index i is used for month_dates[i].
        """
        results = []
        for i, d in enumerate(month_dates):
            recs = provider_records_list[i] if provider_records_list else None
            results.append(self.check_and_run(d, provider_records=recs))
        return results

    def operational_status(self) -> dict:
        """Machine-readable operational status for monitoring.

        Extends ForwardCampaign.status() with runner-level metrics:
          - runner_state: ACTIVE (ran at least once this session) | IDLE
          - next_expected_cycle: ISO date of next due evaluation
          - last_error: last FAILED error message (session only; empty on restart)
          - last_run_at: ISO datetime of last check_and_run call (session only)
          - session_run_count: number of check_and_run calls in this process
        """
        campaign = self._get_campaign()
        base = campaign.status()

        # compute next expected cycle from latest successful cycle
        ledger = campaign.ledger
        latest = ledger.latest_cycle()
        next_due: date | None = None
        if latest and latest.evaluation_date:
            next_due = self._scheduler.next_due(self._spec, _LastEvalStub(latest.evaluation_date))

        base.update(
            {
                "runner_state": "ACTIVE" if self._run_count > 0 else "IDLE",
                "next_expected_cycle": next_due.isoformat() if next_due else None,
                "last_error": self._last_error,
                "last_run_at": self._last_run_at,
                "session_run_count": self._run_count,
                "session_successes": self._session_successes,
                "session_failures": self._session_failures,
            }
        )
        return base

    # ── internal ───────────────────────────────────────────────────────────────

    def _get_campaign(self) -> ForwardCampaign:
        """Resume existing campaign or init fresh one."""
        manifest = self._campaign_dir / "campaign_manifest.json"
        if manifest.exists():
            try:
                return ForwardCampaign.resume(self._spec, self._logic, self._campaign_dir)
            except Exception:
                pass
        return ForwardCampaign.init(
            self._spec,
            self._logic,
            data_dir=self._campaign_dir,
            universe=self._universe,
            starting_capital=self._starting_capital,
            campaign_id=self._campaign_id,
        )
