"""Point-in-Time Research Matrix Engine (AIDP Phase 6)."""

from aurelius.market_data.research_matrix.engine import ResearchMatrixEngine
from aurelius.market_data.research_matrix.feature_registry import FEATURES, SOURCES
from aurelius.market_data.research_matrix.quality import check
from aurelius.market_data.research_matrix.schema import ResearchMatrix

__all__ = ["FEATURES", "SOURCES", "ResearchMatrix", "ResearchMatrixEngine", "check"]
