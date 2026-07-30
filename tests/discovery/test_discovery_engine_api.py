"""Integration tests for AlphaDiscoveryEngine and FastAPI Endpoints."""

import pytest
from fastapi.testclient import TestClient

from aurelius.discovery.engine import AlphaDiscoveryEngine
from aurelius.hypothesis.store import HypothesisStore
from aurelius.main import create_app


@pytest.mark.integration
def test_alpha_discovery_engine_run_cycle(tmp_path):
    hyp_store = HypothesisStore(str(tmp_path / "hypothesis.duckdb"))
    engine = AlphaDiscoveryEngine(hypotheses=hyp_store)

    result = engine.run_discovery_cycle(candidate_limit=3)

    assert result.candidates_generated == 3
    assert len(result.approved_hypotheses) + len(result.rejected_hypotheses) == 3

    for approved in result.approved_hypotheses:
        # Verify submitted to HypothesisStore
        records = hyp_store.search(limit=10)
        found = any(r.id == approved.id for r in records)
        assert found, f"Approved hypothesis {approved.id} not found in HypothesisStore"


@pytest.mark.integration
def test_discovery_fastapi_endpoints():
    app = create_app()
    client = TestClient(app)

    # 1. Synthesize endpoint
    resp = client.get("/discovery/synthesize")
    assert resp.status_code == 200
    data = resp.json()
    assert "common_themes" in data
    assert "research_gaps" in data

    # 2. Run cycle endpoint
    resp = client.post("/discovery/run", json={"candidate_limit": 2})
    assert resp.status_code == 200
    cycle_data = resp.json()
    assert cycle_data["candidates_generated"] == 2

    # 3. List hypotheses endpoint
    resp = client.get("/discovery/hypotheses")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
