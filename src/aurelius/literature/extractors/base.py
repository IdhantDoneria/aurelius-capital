"""Abstract base for all literature source extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from aurelius.literature.models import Paper


class SourceExtractor(ABC):
    source: str  # set as class attribute in each subclass

    @abstractmethod
    def fetch(self, limit: int = 100, since: date | None = None) -> list[Paper]:
        """Fetch papers from source. Enrichment fields are empty on return."""
        ...
