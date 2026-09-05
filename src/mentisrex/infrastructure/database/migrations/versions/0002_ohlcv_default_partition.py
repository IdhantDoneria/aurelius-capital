"""OHLCV arbitrary historical dates: DEFAULT partition.

Revision: 0002
Down revision: 0001

Problem this fixes
------------------
`0001` created monthly partitions for `market_data_ohlcv` only over
range(2020, 2027) and gave the table NO default partition. PostgreSQL rejects
any INSERT whose timestamp falls outside a declared partition
("no partition of relation ... found for row"), so ingesting a bar dated before
2020 or after 2026 failed outright. Historical depth was hard-capped at that
fixed 7-year calendar window.

Fix
---
Attach a DEFAULT partition. Any row outside the declared monthly partitions now
lands here instead of erroring, so ingestion accepts arbitrary historical dates.

Query performance is preserved:
  - The declared 2020-2026 monthly partitions are untouched, so queries over the
    hot window still get full partition pruning.
  - A partitioned table's indexes (ix_ohlcv_symbol_ts_freq btree,
    ix_ohlcv_ts_brin) are propagated to every partition automatically, including
    this DEFAULT one — so (symbol_id, timestamp, frequency) lookups and BRIN
    range scans stay index-backed for out-of-window dates too.

# ponytail: all out-of-window rows share ONE default partition, so a query
# confined to a cold sub-range (e.g. only 2005) scans the whole default rather
# than a pruned month. Fine for daily OHLCV via the composite index. If a real
# multi-decade load profiles slow here, upgrade path = create the specific
# monthly partition on demand at ingest time and let rows migrate out of default.
# Note: once the default holds rows for a month, adding a declared partition for
# that month requires detaching the default, creating the partition, moving those
# rows, then reattaching (Postgres validates the default has no conflicting rows).
"""

from __future__ import annotations

import alembic.op as op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TABLE market_data_ohlcv_default PARTITION OF market_data_ohlcv DEFAULT")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market_data_ohlcv_default")
