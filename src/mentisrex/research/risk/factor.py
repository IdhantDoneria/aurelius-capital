"""Factor risk framework (AIDP M13) — dependency-injected.

A `FactorModel` maps asset returns to factor exposures (betas) via OLS and
decomposes portfolio variance into systematic (factor) and specific (idiosyncratic)
risk. Ships CAPM (single market factor) and a general multi-factor model
(`FamaFrenchModel` / `CustomFactorModel` — same math, different injected factors).
Barra-style risk models are a documented extension (needs a vendor exposure matrix).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from mentisrex.research.risk.models import FactorExposure


class FactorModel(ABC):
    name = "factor"

    @abstractmethod
    def factor_returns(self, ctx: dict) -> tuple: ...

    """Return (factor_names, F) where F is (T, K) factor returns."""

    def analyze(self, weights: dict, asset_returns, ctx: dict | None = None) -> FactorExposure:
        ctx = ctx or {}
        names, F = self.factor_returns(ctx)
        ids = list(weights)
        w = np.array([weights[s] for s in ids], dtype=float)
        R = np.asarray(asset_returns, dtype=float)  # (T, N) aligned to ids
        F = np.atleast_2d(np.asarray(F, dtype=float))
        if F.shape[0] != R.shape[0]:
            F = F.T
        # portfolio return series, regressed on factors
        rp = R @ w
        Fd = F - F.mean(axis=0)
        rpd = rp - rp.mean()
        beta, *_ = np.linalg.lstsq(Fd, rpd, rcond=None)  # (K,)
        resid = rpd - Fd @ beta
        Fcov = np.cov(Fd, rowvar=False)
        Fcov = np.atleast_2d(Fcov)
        sys_var = float(beta @ Fcov @ beta)
        spec_var = float(np.var(resid, ddof=1)) if resid.size > 1 else 0.0
        total = sys_var + spec_var
        contrib = {names[k]: float(beta[k] * (Fcov @ beta)[k]) for k in range(len(names))}
        r2 = sys_var / total if total > 0 else 0.0
        return FactorExposure(
            model=self.name,
            betas={names[k]: float(beta[k]) for k in range(len(names))},
            factor_contribution=contrib,
            factor_risk=float(np.sqrt(max(sys_var, 0.0))),
            specific_risk=float(np.sqrt(max(spec_var, 0.0))),
            r_squared=float(r2),
        )


class CAPMModel(FactorModel):
    """Single market factor. Market returns injected via ctx['market_returns']."""

    name = "capm"

    def factor_returns(self, ctx):
        mkt = ctx.get("market_returns")
        if mkt is None:
            raise ValueError("CAPMModel needs ctx['market_returns']")
        return ["market"], np.asarray(mkt, dtype=float).reshape(-1, 1)


class CustomFactorModel(FactorModel):
    """User-supplied factors. ctx['factor_returns'] (T,K) + ctx['factor_names']."""

    name = "custom"

    def factor_returns(self, ctx):
        F = ctx.get("factor_returns")
        if F is None:
            raise ValueError("CustomFactorModel needs ctx['factor_returns']")
        F = np.asarray(F, dtype=float)
        names = ctx.get("factor_names") or [f"f{i}" for i in range(F.shape[1] if F.ndim > 1 else 1)]
        return list(names), F


class FamaFrenchModel(CustomFactorModel):
    """Fama-French hook — a CustomFactorModel expecting Mkt-RF/SMB/HML(/RMW/CMA/UMD)
    factor-return columns in ctx['factor_returns']. No factor data is bundled; the
    caller injects the series (kept PIT-safe upstream)."""

    name = "fama_french"
