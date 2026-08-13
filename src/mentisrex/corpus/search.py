"""Semantic and hybrid search engine for research corpus documents."""

from typing import Any

from mentisrex.core.logging import get_logger
from mentisrex.corpus.models import CorpusDocument, CorpusSearchResult

logger = get_logger(__name__)

_EMBED_MODEL = "all-MiniLM-L6-v2"
_embedder_cache: Any = None


def _get_embedder() -> Any:
    global _embedder_cache
    if _embedder_cache is not None:
        return _embedder_cache
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import]

        _embedder_cache = SentenceTransformer(_EMBED_MODEL)
        logger.info("corpus_embedder_loaded", model=_EMBED_MODEL)
    except ImportError:
        _embedder_cache = False
        logger.warning("corpus_embedder_unavailable", hint="pip install 'mentisrex-capital[ml]'")
    return _embedder_cache


def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    dot = sum(a * b for a, b in zip(vec1, vec2, strict=False))
    norm1 = sum(a * a for a in vec1) ** 0.5
    norm2 = sum(b * b for b in vec2) ** 0.5
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return float(dot / (norm1 * norm2))


class CorpusSearchEngine:
    """Natural language semantic and hybrid search engine."""

    def __init__(self) -> None:
        self.embeddings_cache: dict[str, list[float]] = {}

    def embed_text(self, text: str) -> list[float]:
        embedder = _get_embedder()
        if embedder:
            try:
                emb = embedder.encode(text).tolist()
                return [float(x) for x in emb]
            except Exception as exc:
                logger.warning("corpus_embed_error", error=str(exc))
        # Simple term frequency fallback vector generator if sentence-transformers unavailable
        words = text.lower().split()
        hash_vec = [0.0] * 64
        for w in words:
            idx = hash(w) % 64
            hash_vec[idx] += 1.0
        norm = sum(x * x for x in hash_vec) ** 0.5 or 1.0
        return [x / norm for x in hash_vec]

    def search(
        self,
        documents: list[CorpusDocument],
        query: str,
        domain_filter: str | None = None,
        asset_class_filter: str | None = None,
        min_quality_score: float = 0.0,
        limit: int = 10,
    ) -> list[CorpusSearchResult]:
        if not query.strip() or not documents:
            return []

        query_vec = self.embed_text(query)
        query_terms = set(query.lower().split())

        results: list[CorpusSearchResult] = []

        for doc in documents:
            # Apply filters
            if doc.classification:
                if domain_filter and doc.classification.research_domain != domain_filter:
                    continue
                if asset_class_filter and asset_class_filter not in [
                    ac.value for ac in doc.classification.asset_classes
                ]:
                    continue
                if doc.classification.quality_score < min_quality_score:
                    continue

            # Compute semantic vector similarity
            doc_text = f"{doc.title} {doc.abstract} {' '.join(doc.authors)}"
            if doc.id not in self.embeddings_cache:
                self.embeddings_cache[doc.id] = self.embed_text(doc_text)

            sem_score = _cosine_similarity(query_vec, self.embeddings_cache[doc.id])

            # Compute BM25 / token match score
            doc_terms = set(doc_text.lower().split())
            common = query_terms.intersection(doc_terms)
            token_score = len(common) / max(1, len(query_terms))

            # Combined hybrid score
            hybrid_score = round(0.7 * sem_score + 0.3 * token_score, 4)

            snippet = doc.abstract[:200] + "..." if len(doc.abstract) > 200 else doc.abstract
            if not snippet:
                snippet = doc.title

            if hybrid_score > 0.05 or any(term in doc_text.lower() for term in query_terms):
                results.append(
                    CorpusSearchResult(
                        doc_id=doc.id,
                        title=doc.title,
                        doc_type=doc.doc_type,
                        classification=doc.classification,
                        score=hybrid_score,
                        snippet=snippet,
                        match_type="semantic" if sem_score > token_score else "hybrid",
                    )
                )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]
