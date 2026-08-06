"""Research matrix data types (AIDP Phase 6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd


@dataclass(frozen=True)
class ResearchMatrix:
    """One reproducible PIT research snapshot.

    `frame` is indexed by security_id; each column is a registered feature. The
    metadata fields pin the snapshot: change the universe, the feature set, or any
    source's data_version and you get a different (cache-distinct) matrix.
    """

    as_of_date: date
    universe_size: int
    data_versions: dict
    generated_at: datetime
    frame: pd.DataFrame
    directions: dict = field(default_factory=dict)  # feature → "higher"|"lower"

    @property
    def metadata(self) -> dict:
        return {
            "as_of_date": self.as_of_date,
            "universe_size": self.universe_size,
            "data_versions": self.data_versions,
            "generated_at": self.generated_at,
        }
