"""Unit tests for QuantTaxonomy."""

from aurelius.corpus.taxonomy import QuantTaxonomy


def test_taxonomy_domains_exist() -> None:
    domains = QuantTaxonomy.get_all_domains()
    assert len(domains) >= 16
    assert "market_microstructure" in domains
    assert "statistical_methodology" in domains
    assert "econometrics" in domains
    assert "machine_learning" in domains
    assert "optimization" in domains
    assert "portfolio_theory" in domains
    assert "risk_management" in domains
    assert "alternative_data" in domains
    assert "execution_research" in domains


def test_taxonomy_domain_info() -> None:
    info = QuantTaxonomy.get_domain_info("market_microstructure")
    assert info is not None
    assert "subdomains" in info
    assert "order_book_dynamics" in info["subdomains"]
    assert len(info["keywords"]) > 5


def test_taxonomy_factors_and_methods() -> None:
    factors = QuantTaxonomy.get_factors()
    assert len(factors) >= 10
    factor_ids = [f["id"] for f in factors]
    assert "value" in factor_ids
    assert "momentum" in factor_ids
    assert "quality" in factor_ids

    methods = QuantTaxonomy.get_statistical_methods()
    assert len(methods) >= 10
    assert "OLS Regression" in methods
    assert "GARCH / EGARCH" in methods
