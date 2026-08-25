"""The three candidate swing/intraday strategies.

Each is built on a *different* economic source of short-horizon return, so
that the comparison is informative rather than three views of one factor:

  nightfall  -- clientele segmentation across the overnight/intraday boundary
  dayburn    -- underreaction to intraday information in high-attention names
  lastlight  -- liquidity provision against mechanical closing-auction flow
"""
from .nightfall import Nightfall, NightfallConfig
from .dayburn import Dayburn, DayburnConfig
from .lastlight import Lastlight, LastlightConfig

__all__ = [
    "Nightfall", "NightfallConfig",
    "Dayburn", "DayburnConfig",
    "Lastlight", "LastlightConfig",
]
