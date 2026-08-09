"""Continuous risk monitoring (AIDP M13).

Turns a time-ordered sequence of `RiskReport`s into a `RiskSnapshot` timeline and
detects risk events/alerts: limit breach, exposure drift, drawdown breach,
volatility spike, liquidity deterioration, concentration increase. Pure over the
supplied reports — no state, deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass

from aurelius.research.risk.models import RiskAlert, RiskDecision, RiskEvent, RiskSnapshot


@dataclass(frozen=True)
class MonitorThresholds:
    exposure_drift: float = 0.20          # abs gross change tick-to-tick
    vol_spike: float = 1.5                # vol > 1.5× trailing mean
    concentration_increase: float = 0.05  # HHI rise tick-to-tick
    liquidity_signal: str = "critical"


def snapshot(report) -> RiskSnapshot:
    return RiskSnapshot(
        as_of=report.as_of, volatility=report.volatility,
        gross=report.exposure.gross, net=report.exposure.net,
        var_95=(report.var.var.get("95%", 0.0) if report.var else 0.0),
        herfindahl=report.concentration.herfindahl,
        max_drawdown=(report.drawdown.max_drawdown if report.drawdown else 0.0),
        n_violations=len(report.violations))


def monitor(reports, *, thresholds: MonitorThresholds | None = None) -> dict:
    t = thresholds or MonitorThresholds()
    timeline = [snapshot(r) for r in reports]
    alerts: list[RiskAlert] = []
    events: list[RiskEvent] = []
    trailing_vol: list[float] = []
    for i, r in enumerate(reports):
        prev = reports[i - 1] if i else None
        if r.violations:
            events.append(RiskEvent(r.as_of, "limit_breach",
                                    {"violations": [v.message for v in r.violations]}))
            for v in r.violations:
                alerts.append(RiskAlert(r.as_of, "limit_breach", v.message,
                                        "critical" if v.severity == "hard" else "warning"))
        if r.decision == RiskDecision.REJECT:
            alerts.append(RiskAlert(r.as_of, "decision_reject", "risk decision REJECT", "critical"))
        if r.drawdown and r.drawdown.halt_triggered:
            events.append(RiskEvent(r.as_of, "drawdown_breach",
                                    {"current": r.drawdown.current_drawdown}))
            alerts.append(RiskAlert(r.as_of, "drawdown_breach",
                                    f"drawdown halt {r.drawdown.current_drawdown:.3f}", "critical"))
        if prev and abs(r.exposure.gross - prev.exposure.gross) > t.exposure_drift:
            events.append(RiskEvent(r.as_of, "exposure_drift",
                                    {"from": prev.exposure.gross, "to": r.exposure.gross}))
            alerts.append(RiskAlert(r.as_of, "exposure_drift",
                                    f"gross {prev.exposure.gross:.2f}->{r.exposure.gross:.2f}", "warning"))
        if trailing_vol and r.volatility > t.vol_spike * (sum(trailing_vol) / len(trailing_vol)):
            events.append(RiskEvent(r.as_of, "vol_spike", {"volatility": r.volatility}))
            alerts.append(RiskAlert(r.as_of, "vol_spike", f"vol spike {r.volatility:.3f}", "warning"))
        if prev and r.concentration.herfindahl - prev.concentration.herfindahl > t.concentration_increase:
            alerts.append(RiskAlert(r.as_of, "concentration_increase",
                                    f"HHI {prev.concentration.herfindahl:.3f}->"
                                    f"{r.concentration.herfindahl:.3f}", "warning"))
        if r.liquidity and r.liquidity.liquidity_signal == t.liquidity_signal:
            alerts.append(RiskAlert(r.as_of, "liquidity_deterioration",
                                    f"liquidity {r.liquidity.liquidity_signal}", "warning"))
        if r.volatility > 0:
            trailing_vol.append(r.volatility)
            trailing_vol[:] = trailing_vol[-20:]
    return {"timeline": timeline, "alerts": alerts, "events": events,
            "n_alerts": len(alerts), "n_events": len(events)}
