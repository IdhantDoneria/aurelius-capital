"""Unit tests for HypothesisStore (in-memory DuckDB)."""
import pytest
from datetime import UTC, datetime

from aurelius.hypothesis.models import HypothesisRecord
from aurelius.hypothesis.store import HypothesisStore


def _record(id_: str = "h001", statement: str = "IF momentum high THEN equity returns positive OVER 1_month") -> HypothesisRecord:
    now = datetime.now(UTC)
    return HypothesisRecord(
        id=id_,
        parent_papers=["paper-001"],
        research_category="factor_anomaly",
        economic_intuition="Momentum persists due to underreaction.",
        testable_statement=statement,
        expected_behavior="Top decile outperforms.",
        asset_classes=["equities"],
        required_datasets=["CRSP"],
        required_features=["momentum_12_1"],
        holding_period="1_month",
        expected_risks=["momentum_crash"],
        confidence_score=0.75,
        assumptions=["Markets not fully efficient"],
        dependencies=[],
        validation_requirements=["Sharpe > 0.5"],
        status="Draft",
        version=1,
        created_at=now,
        updated_at=now,
        researcher="llm",
        generation_method="llm",
    )


@pytest.fixture
def store() -> HypothesisStore:
    return HypothesisStore(":memory:")


@pytest.mark.unit
def test_insert_new(store: HypothesisStore) -> None:
    assert store.insert(_record()) is True


@pytest.mark.unit
def test_insert_duplicate_returns_false(store: HypothesisStore) -> None:
    h = _record()
    store.insert(h)
    assert store.insert(h) is False


@pytest.mark.unit
def test_get_roundtrip(store: HypothesisStore) -> None:
    h = _record()
    store.insert(h)
    got = store.get(h.id)
    assert got is not None
    assert got.testable_statement == h.testable_statement
    assert got.asset_classes == ["equities"]
    assert got.confidence_score == 0.75


@pytest.mark.unit
def test_update_increments_version(store: HypothesisStore) -> None:
    h = _record()
    store.insert(h)
    h.status = "Active"
    store.update(h)
    got = store.get(h.id)
    assert got is not None
    assert got.version == 2
    assert got.status == "Active"


@pytest.mark.unit
def test_update_saves_version_snapshot(store: HypothesisStore) -> None:
    h = _record()
    store.insert(h)
    h.status = "Active"
    store.update(h)
    versions = store.get_versions(h.id)
    assert len(versions) == 2
    assert versions[0]["version"] == 1
    assert versions[1]["version"] == 2


@pytest.mark.unit
def test_update_nonexistent_raises(store: HypothesisStore) -> None:
    h = _record()
    with pytest.raises(KeyError):
        store.update(h)


@pytest.mark.unit
def test_search_by_query(store: HypothesisStore) -> None:
    h1 = _record("h1", "IF momentum signal high THEN equity returns positive OVER 1_month")
    h2 = _record("h2", "IF yield curve inverts THEN recession probability increases OVER 6_months")
    h2.economic_intuition = "Yield curve inversion predicts recessions via credit channel."
    store.insert(h1)
    store.insert(h2)
    results = store.search(query="momentum")
    assert len(results) == 1
    assert "momentum" in results[0].testable_statement.lower()


@pytest.mark.unit
def test_search_by_status(store: HypothesisStore) -> None:
    h = _record()
    store.insert(h)
    h.status = "Rejected"
    h.rejection_reason = "too_vague"
    store.update(h)
    results = store.search(status="Rejected")
    assert len(results) == 1


@pytest.mark.unit
def test_search_by_category(store: HypothesisStore) -> None:
    store.insert(_record("h1"))
    results = store.search(category="factor_anomaly")
    assert len(results) == 1
    results = store.search(category="macro")
    assert len(results) == 0


@pytest.mark.unit
def test_get_by_paper(store: HypothesisStore) -> None:
    store.insert(_record("h1"))
    store.insert(_record("h2", "IF value signal low THEN bonds outperform OVER 3_months"))
    results = store.get_by_paper("paper-001")
    assert len(results) == 2


@pytest.mark.unit
def test_all_statements(store: HypothesisStore) -> None:
    store.insert(_record("h1"))
    store.insert(_record("h2", "IF value factor high THEN returns positive OVER 3_months"))
    stmts = store.all_statements()
    assert len(stmts) == 2
    assert all(isinstance(s[0], str) and isinstance(s[1], str) for s in stmts)


@pytest.mark.unit
def test_rejected_excluded_from_all_statements(store: HypothesisStore) -> None:
    h = _record("h1")
    store.insert(h)
    h.status = "Rejected"
    h.rejection_reason = "too_vague"
    store.update(h)
    stmts = store.all_statements()
    assert len(stmts) == 0


@pytest.mark.unit
def test_stats(store: HypothesisStore) -> None:
    store.insert(_record("h1"))
    h2 = _record("h2", "IF value factor high THEN returns positive OVER 3_months")
    h2.status = "Rejected"
    h2.rejection_reason = "too_vague"
    store.insert(h2)
    s = store.stats()
    assert s["total"] == 2
    assert s["by_status"]["Draft"] == 1
    assert s["by_status"]["Rejected"] == 1
