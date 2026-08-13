"""Fill processing (AIDP M14).

Maps broker fills back to their parent order, applies them to the OMS lifecycle and
(optionally) into the M12 internal book — with duplicate-fill protection. The M12
book's own `ingest_fill` is also idempotent; this is a second guard at the execution
layer so a duplicate never reaches the OMS audit trail either. No accounting here —
the book is M11/M12's.
"""

from __future__ import annotations

from mentisrex.research.execution.ems.models import BrokerFill, Fill


class FillProcessor:
    def __init__(self) -> None:
        self._seen: set = set()
        self.duplicates: list = []
        self.processed: list = []            # list[Fill]

    def process(self, bf: BrokerFill, *, parent_id: str, child_id: str, oms, book=None) -> Fill | None:
        """Apply one broker fill. Returns the mapped `Fill`, or None if it's a
        duplicate (already seen fill_id) — recorded in `duplicates`."""
        if bf.fill_id in self._seen:
            self.duplicates.append(bf.fill_id)
            return None
        self._seen.add(bf.fill_id)
        oms.record_fill(parent_id, bf.quantity, bf.price, bf.cost, when=bf.when, fill_id=bf.fill_id)
        if book is not None:
            book.ingest_fill(bf)             # M12 accounting, idempotent
        fill = Fill(fill_id=bf.fill_id, order_id=parent_id, child_order_id=child_id,
                    security_id=bf.security_id, quantity=bf.quantity, price=bf.price,
                    cost=bf.cost, when=bf.when)
        self.processed.append(fill)
        return fill

    @property
    def n_duplicates(self) -> int:
        return len(self.duplicates)
