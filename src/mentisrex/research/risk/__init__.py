"""Institutional Risk Engine (AIDP M13).

Canonical, PIT-safe, dependency-injected risk layer that consolidates and
supersedes the legacy Platform-Track risk engine (`mentisrex.risk`, historical,
untouched). Answers: within limits? where does risk come from? what exposures?
what under stress? block a trade? deployable? Reuses M10 covariance/risk-contribution,
M11 drawdown/exposure, M9 validation; independent of alpha and execution. Plugs into
the M12 paper-trading gate by injection (`RiskEngine.as_gate()`).
"""

from mentisrex.research.risk.capacity import capacity_report
from mentisrex.research.risk.concentration import concentration_report
from mentisrex.research.risk.covariance import (
    EWMACovariance,
    FactorCovariance,
    make_covariance,
)
from mentisrex.research.risk.diagnostics import diagnostics, fingerprint
from mentisrex.research.risk.drawdown import drawdown_report, should_halt
from mentisrex.research.risk.engine import RiskEngine, RiskEngineConfig, RiskGate
from mentisrex.research.risk.exposure import exposure_report
from mentisrex.research.risk.factor import (
    CAPMModel,
    CustomFactorModel,
    FactorModel,
    FamaFrenchModel,
)
from mentisrex.research.risk.limits import RiskLimits
from mentisrex.research.risk.liquidity import liquidity_report
from mentisrex.research.risk.models import (
    CapacityReport,
    ConcentrationReport,
    DeploymentRiskDecision,
    DrawdownReport,
    ExposureReport,
    FactorExposure,
    LiquidityReport,
    PortfolioHealthReport,
    RiskAlert,
    RiskDecision,
    RiskEvent,
    RiskLimit,
    RiskReport,
    RiskSnapshot,
    RiskValidationResult,
    RiskViolation,
    StressResult,
    StressScenario,
    StressTestReport,
    VaRReport,
)
from mentisrex.research.risk.monitoring import MonitorThresholds, monitor
from mentisrex.research.risk.registry import attach_risk
from mentisrex.research.risk.stress import HISTORICAL_SCENARIOS, apply_scenario, stress_test
from mentisrex.research.risk.validation import (
    deployment_risk_decision,
    portfolio_health,
    validate_risk,
)
from mentisrex.research.risk.var import historical_var, parametric_var

__all__ = [
    "RiskEngine", "RiskEngineConfig", "RiskGate", "RiskLimits",
    "exposure_report", "concentration_report", "liquidity_report", "capacity_report",
    "drawdown_report", "should_halt", "historical_var", "parametric_var",
    "stress_test", "apply_scenario", "HISTORICAL_SCENARIOS",
    "make_covariance", "EWMACovariance", "FactorCovariance",
    "FactorModel", "CAPMModel", "FamaFrenchModel", "CustomFactorModel",
    "monitor", "MonitorThresholds", "attach_risk",
    "validate_risk", "portfolio_health", "deployment_risk_decision",
    "diagnostics", "fingerprint",
    # models
    "RiskDecision", "RiskLimit", "RiskViolation", "RiskSnapshot", "RiskReport",
    "ExposureReport", "FactorExposure", "ConcentrationReport", "LiquidityReport",
    "CapacityReport", "VaRReport", "StressTestReport", "StressResult", "StressScenario",
    "DrawdownReport", "PortfolioHealthReport", "RiskAlert", "RiskEvent",
    "DeploymentRiskDecision", "RiskValidationResult",
]
