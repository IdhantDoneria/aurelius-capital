"""FastAPI router for the Data Intelligence Platform catalog endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from mentisrex.catalog.governance import GovernanceManager
from mentisrex.catalog.lineage import LineageTracker
from mentisrex.catalog.models import DatasetRecord, LineageEdge
from mentisrex.catalog.monitor import HealthMonitor
from mentisrex.catalog.quality import QualityEngine
from mentisrex.catalog.store import CatalogStore
from mentisrex.catalog.versioning import VersionManager

catalog_router = APIRouter(prefix="/catalog", tags=["data-catalog"])

_store: CatalogStore | None = None


def get_catalog() -> CatalogStore:
    global _store
    if _store is None:
        from mentisrex.infrastructure.config.settings import get_settings

        settings = get_settings()
        _store = CatalogStore(settings.catalog_path)
        _store.bootstrap()
    return _store


# ── Datasets ──────────────────────────────────────────────────────────────────


@catalog_router.get("/datasets", response_model=list[DatasetRecord])
def list_datasets(
    source: str | None = None,
    asset_class: str | None = None,
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[DatasetRecord]:
    return get_catalog().list_datasets(source=source, asset_class=asset_class, status=status, limit=limit)


@catalog_router.post("/datasets", response_model=DatasetRecord, status_code=201)
def register_dataset(record: DatasetRecord) -> DatasetRecord:
    try:
        return get_catalog().register(record)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@catalog_router.get("/datasets/{dataset_id}", response_model=DatasetRecord)
def get_dataset(dataset_id: str) -> DatasetRecord:
    ds = get_catalog().get(dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id!r} not found")
    return ds


@catalog_router.put("/datasets/{dataset_id}", response_model=DatasetRecord)
def update_dataset(dataset_id: str, updates: dict) -> DatasetRecord:
    catalog = get_catalog()
    ds = catalog.get(dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id!r} not found")
    updated = ds.model_copy(update=updates)
    return catalog.register(updated)


# ── Lineage ───────────────────────────────────────────────────────────────────


@catalog_router.get("/datasets/{dataset_id}/lineage")
def get_lineage(dataset_id: str) -> dict:
    return LineageTracker(get_catalog()).impact_analysis(dataset_id)


@catalog_router.post("/lineage", response_model=LineageEdge, status_code=201)
def add_lineage_edge(edge: LineageEdge) -> LineageEdge:
    try:
        return get_catalog().add_lineage_edge(edge)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Versions ──────────────────────────────────────────────────────────────────


@catalog_router.get("/datasets/{dataset_id}/versions")
def list_versions(dataset_id: str) -> list[dict]:
    return [v.model_dump() for v in get_catalog().list_versions(dataset_id)]


class SnapshotRequest(BaseModel):
    db_path: str
    table: str
    created_by: str = "system"
    notes: str = ""


@catalog_router.post("/datasets/{dataset_id}/snapshot")
def snapshot_dataset(dataset_id: str, req: SnapshotRequest) -> dict:
    catalog = get_catalog()
    if not catalog.get(dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id!r} not found")
    try:
        v = VersionManager(catalog).snapshot(
            dataset_id, req.db_path, req.table,
            created_by=req.created_by, notes=req.notes,
        )
        return v.model_dump()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Quality ───────────────────────────────────────────────────────────────────


class QualityRunRequest(BaseModel):
    db_path: str
    table: str
    date_col: str = "timestamp"
    symbol_col: str | None = "symbol"
    value_cols: list[str] = []
    freshness_days: int = 1


@catalog_router.post("/datasets/{dataset_id}/quality")
def run_quality_check(dataset_id: str, req: QualityRunRequest) -> dict:
    catalog = get_catalog()
    ds = catalog.get(dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id!r} not found")
    try:
        report = QualityEngine(catalog).run(
            ds, req.db_path, req.table,
            date_col=req.date_col, symbol_col=req.symbol_col,
            value_cols=req.value_cols or None, freshness_days=req.freshness_days,
        )
        return report.model_dump()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Governance ────────────────────────────────────────────────────────────────


@catalog_router.get("/datasets/{dataset_id}/governance")
def get_governance(dataset_id: str) -> list[dict]:
    return [r.model_dump() for r in GovernanceManager(get_catalog()).get_history(dataset_id)]


@catalog_router.post("/datasets/{dataset_id}/deprecate")
def deprecate_dataset(
    dataset_id: str,
    actor: str = "system",
    reason: str = "",
    replaced_by: str | None = None,
) -> dict:
    catalog = get_catalog()
    if not catalog.get(dataset_id):
        raise HTTPException(status_code=404, detail=f"Dataset {dataset_id!r} not found")
    rec = GovernanceManager(catalog).deprecate(dataset_id, actor, reason, replaced_by)
    return rec.model_dump()


# ── Monitoring ────────────────────────────────────────────────────────────────


@catalog_router.get("/health")
def catalog_health() -> dict:
    return HealthMonitor(get_catalog()).generate_report()


# ── Search ────────────────────────────────────────────────────────────────────


@catalog_router.get("/search", response_model=list[DatasetRecord])
def search_datasets(q: str = Query(..., min_length=1)) -> list[DatasetRecord]:
    return get_catalog().search(q)
