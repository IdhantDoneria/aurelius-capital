"""RiskEngine — canonical institutional risk orchestrator (AIDP M13).

Composes the M13 analytics (exposure, concentration, covariance, VaR, drawdown,
factor, liquidity, capacity) into one `RiskReport` and a `RiskDecision`, and
exposes a pre-trade gate that plugs into the M12 paper-trading session by
dependency injection (same `.check(orders, state, prices)` contract) — so "the M12
gate uses M13" with no change to certified M12 code.

Scale-safe: portfolio volatility is the realized portfolio-return vol (correlation-
aware, O(N·T)); risk contributions use the O(N) diagonal model (reused M10
`diagonal_risk_diagnostics`). A dense covariance is only built when a small-N caller
injects one — never materialised for large universes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import numpy as np

from mentisrex.research.portfolio.risk import diagonal_risk_diagnostics
from mentisrex.research.risk import concentration as conc_mod
from mentisrex.research.risk import exposure as exp_mod
from mentisrex.research.risk import var as var_mod
from mentisrex.research.risk.capacity import capacity_report
from mentisrex.research.risk.drawdown import drawdown_report
from mentisrex.research.risk.limits import RiskLimits
from mentisrex.research.risk.liquidity import liquidity_report
from mentisrex.research.risk.models import RiskDecision, RiskReport

PERIODS = 252


@dataclass
class RiskEngineConfig:
    limits: RiskLimits = field(default_factory=RiskLimits)
    var_method: str = "historical"        # historical | parametric
    var_horizon_days: int = 1
    periods_per_year: int = PERIODS
    participation_limit: float = 0.10
    halt_drawdown: float = 0.25


class RiskEngine:
    def __init__(self, config: RiskEngineConfig | None = None, *, factor_model=None) -> None:
        self.config = config or RiskEngineConfig()
        self.factor_model = factor_model

    def assess(self, weights: dict, *, returns=None, values=None, adv=None, aum=None,
               sectors=None, betas=None, factor_ctx=None, turnover=None, when: date | None = None,
               portfolio_value: float | None = None, limits: RiskLimits | None = None) -> RiskReport:
        cfg = self.config
        lim = limits or cfg.limits
        w = weights or {}
        ids = list(w)
        wv = np.array([w[s] for s in ids], dtype=float) if ids else np.array([])

        exposure = exp_mod.exposure_report(w, sectors=sectors)

        # ── volatility + per-name risk contribution (scale-safe) ──
        vol, rc_pct = 0.0, {}
        var_report = None
        if returns is not None and ids:
            R = _align_returns(returns, ids)
            if R.size and R.shape[0] > 1:
                rp = R @ wv
                vol = float(rp.std(ddof=1) * np.sqrt(cfg.periods_per_year))
                var_fn = var_mod.parametric_var if cfg.var_method == "parametric" else var_mod.historical_var
                var_report = var_fn(rp, horizon_days=cfg.var_horizon_days)
                variances = np.var(R, axis=0, ddof=1)
                diag = diagonal_risk_diagnostics(wv, variances)
                rc_pct = {ids[i]: float(diag["pct_risk_contribution"][i]) for i in range(len(ids))}

        concentration = conc_mod.concentration_report(w, risk_contribution=rc_pct)

        dd = drawdown_report(values, halt_threshold=-cfg.halt_drawdown) if values is not None else None

        liq = None
        if adv is not None and (portfolio_value or 0) > 0:
            liq = liquidity_report(w, adv, portfolio_value=portfolio_value,
                                   participation_limit=cfg.participation_limit)
        cap = None
        if adv is not None and aum:
            cap = capacity_report(w, adv, aum=aum, participation_limit=cfg.participation_limit)

        factor = None
        if self.factor_model is not None and returns is not None and ids:
            factor = self.factor_model.analyze(w, _align_returns(returns, ids), factor_ctx)

        metrics = {
            "max_position": float(np.abs(wv).max()) if wv.size else 0.0,
            "gross": exposure.gross, "net_abs": abs(exposure.net), "leverage": exposure.gross,
            "volatility": vol if returns is not None else None,
            "current_drawdown_abs": abs(dd.current_drawdown) if dd else None,
            "var_95": (var_report.var.get("95%") if var_report else None),
            "turnover": turnover,
            "herfindahl": concentration.herfindahl,
            "max_participation": liq.max_participation if liq else None,
            "max_days_to_liquidate": liq.max_days_to_liquidate if liq else None,
        }
        violations = lim.evaluate(metrics)
        decision, warnings = _decide(violations, dd)

        return RiskReport(
            as_of=when, decision=decision, volatility=vol, exposure=exposure,
            concentration=concentration, var=var_report, factor=factor, drawdown=dd,
            liquidity=liq, capacity=cap, violations=violations, warnings=warnings,
            risk_contribution=rc_pct,
            metadata={"var_method": cfg.var_method, "n_positions": len(ids)},
            generated_at=datetime.now(UTC))

    # ── pre-trade gate (M12 integration) ──────────────────────────────────────
    def pre_trade_check(self, target_weights: dict, *, returns=None, values=None,
                        adv=None, aum=None, portfolio_value=None, turnover=None,
                        when=None) -> RiskReport:
        return self.assess(target_weights, returns=returns, values=values, adv=adv, aum=aum,
                           portfolio_value=portfolio_value, turnover=turnover, when=when)

    def as_gate(self, *, adv_provider=None, returns_provider=None):
        return RiskGate(self, adv_provider=adv_provider, returns_provider=returns_provider)


class RiskGate:
    """M12-compatible pre-trade gate. Same `check(orders, state, prices)` contract as
    M12's `PreTradeRiskGate`, so it drops into `PaperTradingSession(risk_gate=…)`.
    Supersedes the M12 gate with the full M13 limit set."""

    def __init__(self, engine: RiskEngine, *, adv_provider=None, returns_provider=None) -> None:
        self.engine = engine
        self.adv_provider = adv_provider
        self.returns_provider = returns_provider

    def check(self, orders, state, prices):
        if not orders:
            return [], []
        value = state.total_value() or 1.0
        # per-name hard position cap first (reject individual offenders)
        proj = {sid: h.shares for sid, h in state.holdings.items()}
        approved, rejected = [], []
        cap = self.engine.config.limits.max_position
        for o in orders:
            p = prices.get(o.security_id)
            if p is None or p <= 0:
                rejected.append((o, "unpriced"))
                continue
            new_shares = proj.get(o.security_id, 0.0) + o.quantity
            if cap is not None and abs(new_shares * p) / value > cap + 1e-9:
                rejected.append((o, "max_position"))
                continue
            proj[o.security_id] = new_shares
            approved.append(o)
        # portfolio-level assessment on the projected book
        tgt = {sid: sh * prices.get(sid, 0.0) / value for sid, sh in proj.items() if sh}
        adv = {sid: self.adv_provider(sid) for sid in tgt} if self.adv_provider else None
        rep = self.engine.assess(tgt, adv=adv, portfolio_value=value)
        if rep.decision == RiskDecision.REJECT:
            return [], [(o, "portfolio_risk_limit") for o in approved] + rejected
        return approved, rejected


def _decide(violations, dd) -> tuple:
    warnings = [v.message for v in violations if v.severity == "soft"]
    if dd and dd.halt_triggered:
        return RiskDecision.REJECT, warnings + ["drawdown halt triggered"]
    if any(v.severity == "hard" for v in violations):
        return RiskDecision.REJECT, warnings
    if warnings:
        return RiskDecision.APPROVE_WITH_WARNING, warnings
    return RiskDecision.APPROVE, warnings


def _align_returns(returns, ids) -> np.ndarray:
    """Accept a {security_id: array} dict or a (T,N) matrix already aligned to ids."""
    if isinstance(returns, dict):
        cols = [np.asarray(returns.get(s, []), dtype=float) for s in ids]
        T = min((c.size for c in cols), default=0)
        if T == 0:
            return np.array([])
        return np.column_stack([c[-T:] for c in cols])
    R = np.asarray(returns, dtype=float)
    return R if R.ndim == 2 else R.reshape(-1, 1)
