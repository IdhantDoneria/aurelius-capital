"""Forward cycle data-quality checks (M30 pre-cycle readiness).

Pure functions and a single dataclass — no I/O.  Call check_snapshot_quality()
with the live snapshot and universe; it returns a DataQualityReport you can
inspect or gate on before submitting Alpaca orders.

Documented data risks for Yahoo Finance / yfinance (see DataRisks):
  ADJUSTMENT     — auto_adjust=True applies *current* adjustments retroactively;
                   a pull next month gives different historical prices for today.
  PIT            — no point-in-time database; yfinance always returns as_of=now.
  DELISTING      — delisted symbol → empty response, treated as MISSING.
  TICKER_CHANGE  — old ticker may silently return empty response or wrong data.
  CORPORATE_ACT  — splits/dividends in the fetch window inflate apparent returns.
  SURVIVORSHIP   — universe fixed at campaign init; survivorship is forward-only
                   (a delisted stock becomes MISSING in the live feed, recorded).
  REVISION       — provider can silently revise prior-period data at any time.
  CROSS_PROVIDER — Yahoo prices may differ from Bloomberg/Refinitiv by ±0.5%
                   on the same day due to different adjustment methodologies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


# ── documented risk flags ──────────────────────────────────────────────────────

class DataRisks:
    """String constants for documented data risks.

    Each flag that appears in DataQualityReport.known_risks is defined here.
    """
    ADJUSTMENT    = "ADJUSTMENT_RETROACTIVE"
    PIT           = "NO_POINT_IN_TIME_DB"
    DELISTING     = "DELISTING_RISK"
    TICKER_CHANGE = "TICKER_CHANGE_RISK"
    CORPORATE_ACT = "CORPORATE_ACTION_IN_WINDOW"
    SURVIVORSHIP  = "SURVIVORSHIP_FORWARD_ONLY"
    REVISION      = "PROVIDER_REVISION_POSSIBLE"
    CROSS_PROVIDER = "CROSS_PROVIDER_DISCREPANCY"


# ── report dataclass ──────────────────────────────────────────────────────────

@dataclass
class DataQualityReport:
    """Outcome of a pre-cycle data-quality check.

    Produced by check_snapshot_quality().  Immutable once constructed.
    """

    evaluation_date: date
    universe: list          # expected symbols
    n_expected: int         # len(universe)
    n_present: int          # symbols with non-zero price in snapshot
    n_missing: int          # expected but absent
    n_zero_price: int       # present but price == 0 or negative
    missing_symbols: list   # symbols absent from snapshot
    zero_price_symbols: list  # symbols with price <= 0
    coverage_fraction: float  # n_present / n_expected

    # per-symbol prices (float; 0.0 if missing)
    spot_prices: dict       # symbol → float

    # risk flags always present for Yahoo Finance
    known_risks: list       # list[str] — from DataRisks constants

    # pass/fail for automated gate
    coverage_ok: bool       # True if coverage_fraction >= min_coverage_threshold
    sanity_ok: bool         # True if n_zero_price == 0
    min_coverage_threshold: float

    # human-readable summary
    notes: list = field(default_factory=list)

    def is_healthy(self) -> bool:
        """Return True if all automated gates pass."""
        return self.coverage_ok and self.sanity_ok

    def print_report(self) -> None:
        print()
        print("=== DATA QUALITY REPORT ===")
        print(f"evaluation_date   : {self.evaluation_date}")
        print(f"universe_size     : {self.n_expected}")
        print(f"n_present         : {self.n_present}")
        print(f"n_missing         : {self.n_missing}")
        print(f"n_zero_price      : {self.n_zero_price}")
        print(f"coverage          : {self.coverage_fraction:.1%}"
              f" ({'OK' if self.coverage_ok else 'BELOW_THRESHOLD'})")
        print(f"sanity            : {'OK' if self.sanity_ok else 'FAIL (zero/negative prices)'}")
        print(f"overall           : {'HEALTHY' if self.is_healthy() else 'UNHEALTHY'}")
        if self.missing_symbols:
            print(f"missing_symbols   : {self.missing_symbols}")
        if self.zero_price_symbols:
            print(f"zero_price        : {self.zero_price_symbols}")
        print()
        print("Known data risks (inherent to Yahoo Finance / yfinance):")
        for r in self.known_risks:
            print(f"  [{r}]")
        if self.notes:
            print()
            print("Notes:")
            for n in self.notes:
                print(f"  - {n}")
        print()


# ── checker ───────────────────────────────────────────────────────────────────

def check_snapshot_quality(
    snapshot,
    universe: list[str],
    evaluation_date: date,
    *,
    min_coverage: float = 0.8,
) -> DataQualityReport:
    """Check snapshot data quality against the forward campaign universe.

    Args:
        snapshot: LiveFeed snapshot with .spots dict (symbol → price-like object).
        universe: Expected symbol list.
        evaluation_date: The forward cycle's as_of date.
        min_coverage: Minimum fraction of universe symbols required (default 0.8).

    Returns:
        DataQualityReport — inspect .is_healthy() for go/no-go.
    """
    spots: dict = {}
    if hasattr(snapshot, "spots"):
        spots = dict(snapshot.spots)
    elif isinstance(snapshot, dict):
        spots = snapshot

    def _price(v) -> float:
        if v is None:
            return 0.0
        try:
            return float(v.mid) if hasattr(v, "mid") else float(v)
        except (TypeError, ValueError):
            return 0.0

    spot_prices = {sym: _price(spots.get(sym)) for sym in universe}

    missing = [sym for sym in universe if sym not in spots]
    zero_price = [sym for sym in universe if sym in spots and spot_prices[sym] <= 0.0]

    n_present = len(universe) - len(missing)
    coverage = n_present / len(universe) if universe else 1.0

    notes = []
    if missing:
        notes.append(
            f"Missing symbols may be delisted, ticker-changed, or unavailable "
            f"from provider today: {missing}"
        )
    if zero_price:
        notes.append(
            f"Zero/negative prices indicate bad data or halted trading: {zero_price}"
        )
    notes.append(
        "Yahoo Finance (auto_adjust=True) applies retroactive split/dividend "
        "adjustments. A pull on a future date may return different prices for "
        "today's snapshot. Sealed records capture the snapshot fingerprint at "
        "evaluation time."
    )
    notes.append(
        "No point-in-time database: yfinance always returns 'current as_of=now' "
        "data. Late corporate actions (restated dividends, amended splits) are "
        "reflected immediately in future pulls but NOT in sealed cycle records."
    )

    return DataQualityReport(
        evaluation_date=evaluation_date,
        universe=list(universe),
        n_expected=len(universe),
        n_present=n_present,
        n_missing=len(missing),
        n_zero_price=len(zero_price),
        missing_symbols=missing,
        zero_price_symbols=zero_price,
        coverage_fraction=coverage,
        spot_prices=spot_prices,
        known_risks=[
            DataRisks.ADJUSTMENT,
            DataRisks.PIT,
            DataRisks.DELISTING,
            DataRisks.TICKER_CHANGE,
            DataRisks.CORPORATE_ACT,
            DataRisks.SURVIVORSHIP,
            DataRisks.REVISION,
            DataRisks.CROSS_PROVIDER,
        ],
        coverage_ok=coverage >= min_coverage,
        sanity_ok=len(zero_price) == 0,
        min_coverage_threshold=min_coverage,
        notes=notes,
    )


def check_universe_pit_risks(universe: list[str]) -> list[dict]:
    """Return a list of documented per-symbol PIT risks for the given universe.

    Pure function — no network calls.  Describes risks known at code-write time;
    does NOT query current corporate actions.

    For a pre-cycle network check, use check_snapshot_quality() on a real snapshot.
    """
    # Symbols that have historically had major corporate actions relevant to the
    # forward campaign universe (AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA, JPM,
    # JNJ, V).  This list is documentation only — it does not block execution.
    known_events: dict[str, str] = {
        "GOOGL": "2022-07 20:1 split — yahoo may still adjust older bars retroactively",
        "AMZN":  "2022-06 20:1 split — yahoo may still adjust older bars retroactively",
        "TSLA":  "2022-08 3:1 split — fractional-share behaviour varies by broker",
        "NVDA":  "2024-06 10:1 split — recent; yfinance may return unadjusted data for some windows",
    }
    risks = []
    for sym in universe:
        note = known_events.get(sym, "No major splits in record; monitor corporate actions.")
        risks.append({
            "symbol": sym,
            "pit_risk": DataRisks.PIT,
            "adjustment_risk": DataRisks.ADJUSTMENT,
            "note": note,
        })
    return risks
