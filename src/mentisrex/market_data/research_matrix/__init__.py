"""Point-in-Time Research Matrix Engine (AIDP M6)."""

from mentisrex.market_data.research_matrix.engine import ResearchMatrixEngine
from mentisrex.market_data.research_matrix.feature_registry import FEATURES, SOURCES
from mentisrex.market_data.research_matrix.quality import check
from mentisrex.market_data.research_matrix.schema import ResearchMatrix

__all__ = ["FEATURES", "SOURCES", "ResearchMatrix", "ResearchMatrixEngine", "check"]
