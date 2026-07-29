"""GovernanceManager — access log, retention policies, audit trail, deprecation."""

from __future__ import annotations

from aurelius.catalog.models import GovernanceRecord
from aurelius.catalog.store import CatalogStore
from aurelius.core.logging import get_logger

logger = get_logger(__name__)


class GovernanceManager:
    """Manages the governance lifecycle of datasets."""

    def __init__(self, catalog: CatalogStore) -> None:
        self._catalog = catalog

    def log_access(self, dataset_id: str, actor: str, purpose: str = "") -> GovernanceRecord:
        return self._log(dataset_id, "access", actor, {"purpose": purpose})

    def set_retention(
        self, dataset_id: str, actor: str, retention_days: int
    ) -> GovernanceRecord:
        rec = GovernanceRecord(
            dataset_id=dataset_id,
            action="policy_change",
            actor=actor,
            details={"retention_days": retention_days},
            retention_days=retention_days,
        )
        self._catalog.log_governance(rec)
        logger.info("retention_set", dataset_id=dataset_id, days=retention_days)
        return rec

    def deprecate(
        self,
        dataset_id: str,
        actor: str,
        reason: str,
        replaced_by: str | None = None,
    ) -> GovernanceRecord:
        self._catalog.deprecate(dataset_id, replaced_by)
        return self._log(
            dataset_id,
            "deprecate",
            actor,
            {"reason": reason, "replaced_by": replaced_by},
        )

    def get_history(self, dataset_id: str) -> list[GovernanceRecord]:
        return self._catalog.governance_history(dataset_id)

    def _log(
        self, dataset_id: str, action: str, actor: str, details: dict
    ) -> GovernanceRecord:
        rec = GovernanceRecord(
            dataset_id=dataset_id, action=action, actor=actor, details=details
        )
        self._catalog.log_governance(rec)
        logger.info("governance_event", dataset_id=dataset_id, action=action, actor=actor)
        return rec
