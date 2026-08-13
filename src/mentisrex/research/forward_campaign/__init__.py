"""Forward paper-trading campaign infrastructure (M25).

Provides isolated PAPER_FORWARD operating mode with:
  - Deterministic cycle identity
  - Immutable sealed per-cycle records
  - Duplicate-cycle prevention
  - Forward performance ledger
  - Provider-revision-safe evidence storage
  - Restart / idempotency guarantees
  - No contamination from SIMULATION / BACKTEST / REPLAY state
"""

from mentisrex.research.forward_campaign.record import (
    CycleStatus,
    ForwardCycleRecord,
    make_forward_cycle_id,
)
from mentisrex.research.forward_campaign.ledger import ForwardLedger
from mentisrex.research.forward_campaign.campaign import ForwardCampaign, CampaignConfig

__all__ = [
    "CycleStatus",
    "ForwardCycleRecord",
    "ForwardLedger",
    "ForwardCampaign",
    "CampaignConfig",
    "make_forward_cycle_id",
]
