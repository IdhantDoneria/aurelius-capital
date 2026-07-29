"""Tests for GovernanceManager — access log, retention, deprecation, audit trail."""

import pytest

from aurelius.catalog.governance import GovernanceManager
from aurelius.catalog.models import DatasetRecord
from aurelius.catalog.store import CatalogStore


@pytest.fixture
def catalog() -> CatalogStore:
    store = CatalogStore(":memory:")
    store.register(DatasetRecord(id="ds1", name="DS1", source="yahoo"))
    return store


@pytest.fixture
def manager(catalog: CatalogStore) -> GovernanceManager:
    return GovernanceManager(catalog)


def test_log_access(manager: GovernanceManager) -> None:
    rec = manager.log_access("ds1", actor="researcher_a", purpose="backtesting")
    assert rec.action == "access"
    assert rec.actor == "researcher_a"
    assert rec.details["purpose"] == "backtesting"


def test_set_retention(manager: GovernanceManager) -> None:
    rec = manager.set_retention("ds1", actor="admin", retention_days=365)
    assert rec.action == "policy_change"
    assert rec.retention_days == 365


def test_deprecate_dataset(manager: GovernanceManager, catalog: CatalogStore) -> None:
    manager.deprecate("ds1", actor="admin", reason="superseded", replaced_by="ds2")
    assert catalog.get("ds1").status == "replaced"


def test_deprecate_logs_governance(manager: GovernanceManager) -> None:
    manager.deprecate("ds1", actor="admin", reason="old")
    history = manager.get_history("ds1")
    actions = [r.action for r in history]
    assert "deprecate" in actions


def test_get_history_ordered(manager: GovernanceManager) -> None:
    manager.log_access("ds1", actor="a")
    manager.log_access("ds1", actor="b")
    manager.set_retention("ds1", actor="admin", retention_days=90)
    history = manager.get_history("ds1")
    assert len(history) == 3


def test_get_history_empty(manager: GovernanceManager, catalog: CatalogStore) -> None:
    catalog.register(DatasetRecord(id="fresh", name="Fresh", source="s"))
    assert manager.get_history("fresh") == []


def test_multiple_access_logs(manager: GovernanceManager) -> None:
    for i in range(5):
        manager.log_access("ds1", actor=f"user_{i}")
    history = manager.get_history("ds1")
    assert len(history) == 5
