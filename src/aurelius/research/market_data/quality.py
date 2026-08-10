"""Market-data quality engine (AIDP M19).

Classifies canonical observations against a configurable rule set and returns **structured
diagnostics** — it never silently repairs data. Each finding carries a severity
(INFO/WARNING/ERROR/REJECT); observations tripping a REJECT (or, if configured, ERROR) rule are
moved to `rejected` and never reach valuation. Everything else is retained and marked
VALIDATED/SUSPECT so a caller can decide.

This is the trust boundary: market data is external, so the default posture is fail-closed on
anything that would corrupt a valuation (non-positive price, look-ahead, crossed quote).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from aurelius.research.market_data import diagnostics as diag
from aurelius.research.market_data.models import (
    CanonicalObservation,
    QualityDiagnostic,
    QualityStatus,
    Severity,
    Unit,
)


@dataclass(frozen=True)
class QualityConfig:
    max_staleness_days: int | None = None
    max_spread_frac: float = 0.10
    max_jump_frac: float = 0.5
    reject_severities: tuple = (Severity.REJECT,)   # severities that pull an obs into `rejected`


_PRICE_UNITS = {Unit.PRICE, Unit.FACTOR}


@dataclass(frozen=True)
class QualityReport:
    diagnostics: tuple = ()
    accepted: tuple = ()
    rejected: tuple = ()

    def by_severity(self, sev: Severity) -> list:
        return [d for d in self.diagnostics if d.severity is sev]

    @property
    def ok(self) -> bool:
        return not any(d.severity in (Severity.ERROR, Severity.REJECT) for d in self.diagnostics)


class MarketDataQualityEngine:
    def __init__(self, config: QualityConfig | None = None) -> None:
        self.config = config or QualityConfig()

    def check(self, observations, *, as_of, prior: dict | None = None) -> QualityReport:
        """`prior`: optional {security_id: previous_value} for jump detection."""
        cfg = self.config
        diags: list[QualityDiagnostic] = []
        accepted: list[CanonicalObservation] = []
        rejected: list[CanonicalObservation] = []
        prior = prior or {}

        for obs in observations:
            found: list[QualityDiagnostic] = []

            def add(code, sev, msg):
                found.append(QualityDiagnostic(code, sev, msg, obs.security_id, obs.field))

            # PIT — look-ahead is always fatal for valuation
            m = diag.look_ahead(obs.observation_date, as_of)
            if m:
                add("look_ahead", Severity.REJECT, m)
            m = diag.stale(obs.observation_date, as_of, cfg.max_staleness_days)
            if m:
                add("stale", Severity.WARNING, m)

            # value integrity
            if obs.value is None or obs.value != obs.value:      # None or NaN
                add("missing_value", Severity.REJECT, f"missing/NaN value for {obs.field}")
            elif obs.unit in _PRICE_UNITS and obs.obs_type.value in ("close", "adjusted_close",
                                                                     "trade", "quote", "forward"):
                m = diag.non_positive_price(obs.value)
                if m:
                    add("non_positive_price", Severity.REJECT, m)
            if obs.obs_type.value == "volume":
                m = diag.negative_volume(obs.value)
                if m:
                    add("negative_volume", Severity.ERROR, m)

            # microstructure (bid/ask/OHLC live in meta)
            bid, ask = obs.meta.get("bid"), obs.meta.get("ask")
            m = diag.crossed_quote(bid, ask)
            if m:
                add("crossed_quote", Severity.REJECT, m)
            m = diag.wide_spread(bid, ask, max_frac=cfg.max_spread_frac)
            if m:
                add("wide_spread", Severity.WARNING, m)
            if all(k in obs.meta for k in ("open", "high", "low")):
                m = diag.bad_ohlc(obs.meta["open"], obs.meta["high"], obs.meta["low"], obs.value)
                if m:
                    add("bad_ohlc", Severity.REJECT, m)

            # jump vs prior close
            m = diag.price_jump(prior.get(obs.security_id), obs.value, max_frac=cfg.max_jump_frac)
            if m:
                add("price_jump", Severity.WARNING, m)

            diags.extend(found)
            if any(d.severity in cfg.reject_severities for d in found):
                rejected.append(obs.with_status(QualityStatus.REJECTED))
            elif any(d.severity in (Severity.WARNING, Severity.ERROR) for d in found):
                accepted.append(obs.with_status(QualityStatus.SUSPECT))
            else:
                accepted.append(obs.with_status(QualityStatus.VALIDATED))

        return QualityReport(tuple(diags), tuple(accepted), tuple(rejected))
