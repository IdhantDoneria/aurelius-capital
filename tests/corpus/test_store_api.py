"""Integration tests for CorpusStore and FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient

from mentisrex.corpus.models import VersionType
from mentisrex.corpus.store import CorpusStore
from mentisrex.main import create_app


@pytest.fixture
def store(tmp_path) -> CorpusStore:
    db_file = str(tmp_path / "test_corpus.duckdb")
    return CorpusStore(db_path=db_file)


def test_corpus_store_end_to_end(store: CorpusStore) -> None:
    doc = store.add_document(
        title="Almgren-Chriss Optimal Execution of Portfolio Transactions",
        content="Optimal execution framework balancing volatility risk and market impact.",
        doc_type="market_microstructure",
        authors=["Robert Almgren", "Neil Chriss"],
        venue="Journal of Risk",
        abstract="We consider the problem of optimal execution of portfolio transactions.",
    )

    assert doc.id is not None
    assert doc.classification is not None
    assert doc.classification.research_domain in ["execution_research", "market_microstructure"]
    assert len(doc.versions) == 1

    # Retrieve doc
    fetched = store.get_document(doc.id)
    assert fetched is not None
    assert fetched.title == doc.title

    # Add a summary version
    ver = store.add_version(
        doc_id=doc.id,
        version_type=VersionType.SUMMARY,
        title="Executive Summary",
        content="Key insight: square-root market impact function dictates optimal execution speed.",
    )
    assert ver is not None
    assert ver.version_num == 2

    # Check list documents
    docs = store.list_documents()
    assert len(docs) == 1

    # Search
    results = store.search("market impact optimal execution")
    assert len(results) >= 1
    assert results[0].doc_id == doc.id


def test_fastapi_corpus_routes() -> None:
    app = create_app()
    client = TestClient(app)

    # 1. Get Taxonomy
    res_tax = client.get("/corpus/taxonomy")
    assert res_tax.status_code == 200
    data_tax = res_tax.json()
    assert "market_microstructure" in data_tax["domains"]

    # 2. Acquire Document
    res_acq = client.post(
        "/corpus/documents",
        json={
            "title": "Empirical Asset Pricing via Machine Learning",
            "content": "Comparative evaluation of gradient boosted decision trees and neural networks for equity return prediction.",
            "doc_type": "academic_paper",
            "authors": ["Shihao Gu", "Bryan Kelly", "Dacheng Xiu"],
            "venue": "Review of Financial Studies",
            "abstract": "We measure the empirical performance of machine learning algorithms for asset pricing.",
        },
    )
    assert res_acq.status_code == 200
    doc_data = res_acq.json()
    doc_id = doc_data["id"]
    assert doc_data["classification"]["research_domain"] in ["machine_learning", "academic_papers"]

    # 3. Get Document
    res_get = client.get(f"/corpus/documents/{doc_id}")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == doc_id

    # 4. Add Version
    res_ver = client.post(
        f"/corpus/documents/{doc_id}/versions",
        json={
            "version_type": "summary",
            "title": "RFS Paper Summary",
            "content": "Trees and neural nets dominate linear models in cross-sectional equity return prediction.",
        },
    )
    assert res_ver.status_code == 200
    assert res_ver.json()["version_num"] == 2

    # 5. Search
    res_srch = client.get("/corpus/search?query=machine+learning+asset+pricing")
    assert res_srch.status_code == 200
    srch_data = res_srch.json()
    assert len(srch_data) >= 1
