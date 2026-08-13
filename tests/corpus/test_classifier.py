"""Unit tests for CorpusClassifier."""

from mentisrex.corpus.classifier import CorpusClassifier
from mentisrex.corpus.models import AssetClass, Market


def test_classify_microstructure_paper() -> None:
    classifier = CorpusClassifier()
    res = classifier.classify(
        title="High-Frequency Limit Order Book Dynamics and VPIN Flow Toxicity in Equity Markets",
        abstract="We model limit order book queue position and adverse selection in stock market dark pools using stochastic calculus and Almgren-Chriss market impact.",
        content="Detailed empirical study using GARCH and OLS Regression on equity tick data and liquidity provision in high frequency markets.",
        metadata={"venue": "Journal of Finance"},
    )
    assert res.research_domain == "market_microstructure"
    assert res.subdomain in ["order_book_dynamics", "limit_order_books"]
    assert AssetClass.EQUITY in res.asset_classes
    assert Market.HIGH_FREQUENCY in res.markets
    assert res.quality_score >= 80.0
    assert res.difficulty >= 2
    assert res.novelty >= 3


def test_classify_ml_paper() -> None:
    classifier = CorpusClassifier()
    res = classifier.classify(
        title="Deep Reinforcement Learning for Execution in Crypto Perpetuals",
        abstract="Using PPO transformers and XGBoost feature importance for optimal execution.",
        content="Implementation shortfall reduction with PyTorch neural nets.",
        metadata={"venue": "NeurIPS"},
    )
    assert res.research_domain in ["machine_learning", "execution_research"]
    assert AssetClass.CRYPTO in res.asset_classes
    assert "machine_learning" in res.methodology
    assert res.quality_score >= 80.0
