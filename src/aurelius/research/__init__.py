"""Research experiment framework: hypothesis to verdict, systematically.

    from aurelius.research import ResearchRunner, ResearchStore
    from aurelius.research.templates import MomentumStrategy

    store = ResearchStore(":memory:")
    runner = ResearchRunner(store)
    h = runner.hypothesis("momentum persists", "trend premium", "jdoe")
    report = runner.investigate(h, lambda p: MomentumStrategy(**p),
                                base_params={"lookback": 63}, bars=bars,
                                param_grid={"lookback": [21, 63, 126]})
    print(report.verdict, report.reasons)
"""

from aurelius.research.models import (
    ExperimentRecord,
    Hypothesis,
    ValidationCriteria,
    ValidationReport,
    Verdict,
)
from aurelius.research.runner import ResearchRunner, demo, research_config, synth_bars
from aurelius.research.store import ResearchStore

__all__ = [
    "ExperimentRecord",
    "Hypothesis",
    "ResearchRunner",
    "ResearchStore",
    "ValidationCriteria",
    "ValidationReport",
    "Verdict",
    "demo",
    "research_config",
    "synth_bars",
]
