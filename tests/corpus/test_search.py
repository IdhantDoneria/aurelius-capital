"""Unit tests for CorpusSearchEngine."""

from aurelius.corpus.classifier import CorpusClassifier
from aurelius.corpus.models import CorpusDocument
from aurelius.corpus.search import CorpusSearchEngine


def test_search_relevance() -> None:
    classifier = CorpusClassifier()
    engine = CorpusSearchEngine()

    doc1 = CorpusDocument(
        title="Momentum Strategies in Global FX Markets",
        abstract="Empirical analysis of 12-1 month currency momentum and carry trade interactions.",
        authors=["John Doe"],
    )
    doc1.classification = classifier.classify(doc1.title, doc1.abstract)

    doc2 = CorpusDocument(
        title="Deep Neural Networks for Option Volatility Surface Forecasting",
        abstract="LSTM models predicting implied volatility skew across SPX options.",
        authors=["Jane Smith"],
    )
    doc2.classification = classifier.classify(doc2.title, doc2.abstract)

    docs = [doc1, doc2]

    # Search for FX momentum
    results_fx = engine.search(docs, "currency momentum carry", limit=5)
    assert len(results_fx) > 0
    assert results_fx[0].doc_id == doc1.id

    # Search for options volatility
    results_opt = engine.search(docs, "option volatility neural network", limit=5)
    assert len(results_opt) > 0
    assert results_opt[0].doc_id == doc2.id
