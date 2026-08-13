"""Automated multi-dimensional document classifier."""

from typing import Any

from mentisrex.corpus.models import AssetClass, ClassificationResult, Market
from mentisrex.corpus.taxonomy import QuantTaxonomy


class CorpusClassifier:
    """Classifies quantitative finance documents across 9 core dimensions."""

    def __init__(self) -> None:
        self.taxonomy = QuantTaxonomy

    def classify(
        self,
        title: str,
        abstract: str = "",
        content: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ClassificationResult:
        full_text = f"{title}\n{abstract}\n{content}".lower()
        metadata = metadata or {}

        # 1. Research domain & subdomain
        domain, subdomain = self._classify_domain(full_text)

        # 2. Asset classes
        asset_classes = self._classify_asset_classes(full_text)

        # 3. Methodology
        methodology = self._classify_methodology(full_text)

        # 4. Statistical methods
        stat_methods = self._classify_stat_methods(full_text)

        # 5. Markets
        markets = self._classify_markets(full_text)

        # 6. Factors
        factors = self._classify_factors(full_text)

        # 7. Difficulty (1-5)
        difficulty = self._assess_difficulty(full_text, stat_methods)

        # 8. Novelty (1-5)
        novelty = self._assess_novelty(full_text, metadata)

        # 9. Research quality (0-100)
        quality_score = self._compute_quality_score(full_text, metadata, stat_methods, methodology)

        reasoning = (
            f"Classified into '{domain}' ('{subdomain}') with quality score {quality_score:.1f}/100. "
            f"Difficulty: {difficulty}/5, Novelty: {novelty}/5. Found {len(stat_methods)} stat methods, "
            f"{len(factors)} factors."
        )

        return ClassificationResult(
            research_domain=domain,
            subdomain=subdomain,
            asset_classes=asset_classes,
            methodology=methodology,
            statistical_methods=stat_methods,
            markets=markets,
            factors=factors,
            difficulty=difficulty,
            novelty=novelty,
            quality_score=quality_score,
            reasoning=reasoning,
        )

    def _classify_domain(self, text: str) -> tuple[str, str]:
        scores: dict[str, int] = {}
        for domain_key, domain_info in QuantTaxonomy.DOMAINS.items():
            score = sum(1 for kw in domain_info["keywords"] if kw in text)
            scores[domain_key] = score

        best_domain = (
            max(scores, key=lambda k: scores[k])
            if scores and max(scores.values()) > 0
            else "academic_papers"
        )

        # Match subdomain
        subdomain = "general"
        domain_info = QuantTaxonomy.DOMAINS.get(best_domain, {})
        for sub in domain_info.get("subdomains", []):
            clean_sub = sub.replace("_", " ")
            if clean_sub in text:
                subdomain = sub
                break

        return best_domain, subdomain

    def _classify_asset_classes(self, text: str) -> list[AssetClass]:
        results: list[AssetClass] = []
        mappings = {
            AssetClass.EQUITY: [
                "stock",
                "equity",
                "equities",
                "sp500",
                "s&p 500",
                "nasdaq",
                "nyse",
                "share price",
                "stock market",
                "shares",
                "portfolio transaction",
            ],
            AssetClass.FX: [
                "forex",
                "fx",
                "foreign exchange",
                "currency",
                "eurusd",
                "gbpusd",
                "usdjpy",
            ],
            AssetClass.FIXED_INCOME: [
                "bond",
                "yield curve",
                "treasury",
                "fixed income",
                "sofr",
                "fed funds",
                "credit spread",
            ],
            AssetClass.COMMODITY: [
                "commodity",
                "oil",
                "wti",
                "gold",
                "silver",
                "grain",
                "futures contract",
            ],
            AssetClass.CRYPTO: [
                "crypto",
                "bitcoin",
                "btc",
                "ethereum",
                "eth",
                "blockchain",
                "defi",
            ],
            AssetClass.DERIVATIVE: [
                "option",
                "volatility",
                "vix",
                "swaption",
                "delta hedging",
                "straddle",
                "futures",
            ],
        }
        for ac, keywords in mappings.items():
            if any(kw in text for kw in keywords):
                results.append(ac)

        if not results:
            results.append(AssetClass.MULTI_ASSET)
        return results

    def _classify_methodology(self, text: str) -> str:
        if any(kw in text for kw in ["theorem", "proof", "lemma", "axiom", "proposition"]):
            return "theoretical"
        if any(kw in text for kw in ["monte carlo", "simulated", "simulation"]):
            return "simulation"
        if any(kw in text for kw in ["backtest", "out-of-sample", "historical performance"]):
            return "backtest"
        if any(
            kw in text
            for kw in ["neural net", "deep learning", "machine learning", "reinforcement learning"]
        ):
            return "machine_learning"
        return "empirical"

    def _classify_stat_methods(self, text: str) -> list[str]:
        matched: list[str] = []
        for method in QuantTaxonomy.STATISTICAL_METHODS:
            clean = method.lower()
            tokens = [t for t in clean.split("/") if len(t) > 2]
            if any(tok in text for tok in tokens):
                matched.append(method)
        return matched

    def _classify_markets(self, text: str) -> list[Market]:
        markets: list[Market] = []
        if "sp500" in text or "us equity" in text or "nyse" in text:
            markets.append(Market.US_EQUITIES)
        if "treasury" in text or "us yield" in text:
            markets.append(Market.US_TREASURIES)
        if "crypto" in text or "perpetual" in text:
            markets.append(Market.CRYPTO_PERPETUALS)
        if "options" in text or "vix" in text or "implied volatility" in text:
            markets.append(Market.OPTIONS_VOLATILITY)
        if "hft" in text or "high frequency" in text or "order book" in text:
            markets.append(Market.HIGH_FREQUENCY)

        if not markets:
            markets.append(Market.GLOBAL_EQUITIES)
        return markets

    def _classify_factors(self, text: str) -> list[str]:
        matched: list[str] = []
        for factor in QuantTaxonomy.FACTORS:
            if factor["id"] in text or factor["name"].lower() in text:
                matched.append(factor["id"])
        return matched

    def _assess_difficulty(self, text: str, stat_methods: list[str]) -> int:
        score = 1
        math_terms = [
            "stochastic calculus",
            "ito lemma",
            "pde",
            "hamilton-jacobi-bellman",
            "martingale",
            "measure theory",
        ]
        if any(term in text for term in math_terms):
            score += 2
        if len(stat_methods) >= 3:
            score += 1
        if len(text) > 5000 or "proof" in text:
            score += 1
        return min(5, max(1, score))

    def _assess_novelty(self, text: str, metadata: dict[str, Any]) -> int:
        score = 3
        novelty_keywords = [
            "novel",
            "first time",
            "breakthrough",
            "state-of-the-art",
            "sota",
            "new paradigm",
        ]
        if any(kw in text for kw in novelty_keywords):
            score += 1
        if metadata.get("venue") in [
            "Journal of Finance",
            "Review of Financial Studies",
            "NeurIPS",
        ]:
            score += 1
        return min(5, max(1, score))

    def _compute_quality_score(
        self,
        text: str,
        metadata: dict[str, Any],
        stat_methods: list[str],
        methodology: str,
    ) -> float:
        score = 60.0
        # Journal / venue bonus
        venue = str(metadata.get("venue", "")).lower()
        if any(
            top in venue
            for top in [
                "journal of finance",
                "review of financial studies",
                "jfe",
                "nber",
                "neurips",
            ]
        ):
            score += 20.0
        elif any(
            mid in venue
            for mid in ["ssrn", "arxiv", "quantitative finance", "journal of portfolio management"]
        ):
            score += 10.0

        # Empirical rigor & stat methods bonus
        score += min(15.0, len(stat_methods) * 3.0)

        # Code / dataset availability bonus
        if any(kw in text for kw in ["github", "repository", "data available", "reproducible"]):
            score += 5.0

        return min(100.0, max(0.0, score))
