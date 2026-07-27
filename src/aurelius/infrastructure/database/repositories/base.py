"""Generic async repository base.

All repositories inherit from AbstractRepository[T].
Concrete repositories extend with domain-specific query methods.

Pagination uses keyset (cursor) pagination, not OFFSET.
OFFSET pagination on large tables degrades to O(n) — scanning all rows to skip n.
Keyset pagination is O(log n) — uses the index.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aurelius.core.errors import NotFoundError
from aurelius.infrastructure.database.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


@dataclass(frozen=True)
class PageCursor:
    """Keyset pagination cursor. Encodes position in result set.

    Pass last_id + last_timestamp from previous page to get next page.
    Always use this instead of OFFSET — OFFSET is O(n) on large tables.
    """

    last_id: int | UUID | None = None
    last_value: Any = None  # last sort column value
    page_size: int = 100


@dataclass(frozen=True)
class Page(Generic[ModelT]):  # noqa: UP046
    """Paginated result set with next cursor."""

    items: Sequence[ModelT]
    has_next: bool
    next_cursor: PageCursor | None

    @property
    def count(self) -> int:
        return len(self.items)


class AbstractRepository(ABC, Generic[ModelT]):  # noqa: UP046
    """Base async repository interface."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @abstractmethod
    async def get_by_id(self, id: UUID) -> ModelT | None: ...

    @abstractmethod
    async def save(self, entity: ModelT) -> ModelT: ...

    @abstractmethod
    async def delete(self, id: UUID) -> bool: ...


class BaseRepository(AbstractRepository[ModelT]):
    """Generic SQLAlchemy 2.x async repository.

    Subclass and set `model_class` to get full CRUD for free.
    Override methods for domain-specific behavior.
    """

    model_class: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_id(self, id: UUID) -> ModelT | None:
        result = await self._session.get(self.model_class, id)
        return result

    async def get_by_id_or_raise(self, id: UUID) -> ModelT:
        entity = await self.get_by_id(id)
        if entity is None:
            raise NotFoundError(
                f"{self.model_class.__name__} with id={id} not found",
            )
        return entity

    async def save(self, entity: ModelT) -> ModelT:
        self._session.add(entity)
        await self._session.flush()  # get DB-generated values (id, created_at)
        await self._session.refresh(entity)
        return entity

    async def save_many(self, entities: list[ModelT]) -> list[ModelT]:
        """Bulk save. More efficient than calling save() in a loop."""
        self._session.add_all(entities)
        await self._session.flush()
        return entities

    async def delete(self, id: UUID) -> bool:
        entity = await self.get_by_id(id)
        if entity is None:
            return False
        await self._session.delete(entity)
        await self._session.flush()
        return True

    async def count(self) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(self.model_class)
        )
        return result.scalar_one()
