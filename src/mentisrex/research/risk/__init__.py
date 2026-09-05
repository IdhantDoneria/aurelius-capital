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
    "HISTORICAL_SCENARIOS",
    "CAPMModel",
    "CapacityReport",
    "ConcentrationReport",
    "CustomFactorModel",
    "DeploymentRiskDecision",
    "DrawdownReport",
    "EWMACovariance",
    "ExposureReport",
    "FactorCovariance",
    "FactorExposure",
    "FactorModel",
    "FamaFrenchModel",
    "LiquidityReport",
    "MonitorThresholds",
    "PortfolioHealthReport",
    "RiskAlert",
    # models
    "RiskDecision",
    "RiskEngine",
    "RiskEngineConfig",
    "RiskEvent",
    "RiskGate",
    "RiskLimit",
    "RiskLimits",
    "RiskReport",
    "RiskSnapshot",
    "RiskValidationResult",
    "RiskViolation",
    "StressResult",
    "StressScenario",
    "StressTestReport",
    "VaRReport",
    "apply_scenario",
    "attach_risk",
    "capacity_report",
    "concentration_report",
    "deployment_risk_decision",
    "diagnostics",
    "drawdown_report",
    "exposure_report",
    "fingerprint",
    "historical_var",
    "liquidity_report",
    "make_covariance",
    "monitor",
    "parametric_var",
    "portfolio_health",
    "should_halt",
    "stress_test",
    "validate_risk",
]
