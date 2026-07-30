"""Literature Intelligence Framework — public API."""

from aurelius.literature.enrichment import LLMClient, enrich
from aurelius.literature.models import Paper, paper_id
from aurelius.literature.store import LiteratureStore

__all__ = ["LLMClient", "LiteratureStore", "Paper", "enrich", "paper_id"]
