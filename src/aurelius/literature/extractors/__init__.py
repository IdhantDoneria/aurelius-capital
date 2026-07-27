"""Literature source extractor registry."""
from __future__ import annotations

from aurelius.literature.extractors.arxiv import ArxivExtractor
from aurelius.literature.extractors.base import SourceExtractor
from aurelius.literature.extractors.crossref import CrossRefExtractor
from aurelius.literature.extractors.nber import NBERExtractor

SOURCES = ["arxiv", "nber", "ssrn", "jf", "jfe", "rfs", "qf"]


def get_extractor(source: str) -> SourceExtractor:
    """Return an instantiated extractor for the given source name."""
    match source:
        case "arxiv":
            return ArxivExtractor()
        case "nber":
            return NBERExtractor()
        case "ssrn" | "jf" | "jfe" | "rfs" | "qf":
            return CrossRefExtractor(source)
        case _:
            raise ValueError(f"Unknown source '{source}'. Valid: {SOURCES}")


__all__ = ["SourceExtractor", "ArxivExtractor", "NBERExtractor", "CrossRefExtractor",
           "SOURCES", "get_extractor"]
