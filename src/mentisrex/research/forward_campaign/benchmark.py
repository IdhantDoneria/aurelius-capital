"""SPY benchmark portfolio for forward evidence accumulation (M27).

Tracks a passive buy-and-hold SPY position alongside the PAPER_FORWARD
strategy campaign.  Each cycle produces a sealed BenchmarkCycleRecord
stored in {campaign_dir}/benchmark/{cycle_id}.json.

Design constraints:
  - Benchmark is PASSIVE: no strategy signals affect it.
  - Benchmark accounting is SEPARATE from strategy accounting.
  - Benchmark cannot alter strategy orders; strategy cannot alter benchmark NAV.
  - Sealed records are immutable: once written, never overwritten.
  - PIT enforced: benchmark price at as_of must be <= as_of (no future data).
  - Dividend treatment: PRICE RETURN ONLY.  Yahoo Finance adjusted-close
    prices are not used here to avoid retroactive adjustments corrupting sealed
    forward records.  The limitation is explicitly documented.
  - Provider revision semantics: sealed records are never mutated even if
    Yahoo later revises a historical price.

Data limitation (explicit):
  Yahoo Finance (yfinance) — free/public, NOT institutional/exchange-grade.
  Dividends are NOT captured: this is a price-return benchmark only.
  Adjusted-close prices are intentionally avoided to keep sealed records
  from being silently mutated by retroactive provider adjustments.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional


_BENCHMARK_SYMBOL = "SPY"
_BENCHMARK_DATA_LIMITATION = (
    "Yahoo Finance (yfinance) — free/public, NOT institutional/exchange-grade. "
    "PRICE RETURN ONLY: dividends are NOT captured. "
    "Adjusted-close is avoided to prevent retroactive provider revisions from "
    "mutating sealed forward records. "
    "Retroactive adjustments may occur but sealed benchmark records are immutable."
)


# ── sealed per-cycle record ───────────────────────────────────────────────────

@dataclass
class BenchmarkCycleRecord:
    """Sealed, immutable record of benchmark state for one forward cycle.

    One record per evaluation cycle, keyed by cycle_id (same identifier used
    by ForwardCycleRecord).  Sealing is irreversible.

    Accounting invariant: cash + shares * spy_price == ending_nav (within fp).
    """

    # IDENTITY
    cycle_id: str = ""
    benchmark_symbol: str = _BENCHMARK_SYMBOL
    evaluation_date: Optional[date] = None
    knowledge_as_of: Optional[date] = None
    campaign_id: str = ""
    mode: str = "PAPER_FORWARD"

    # PRICE
    spy_price: float = 0.0            # benchmark price at this evaluation
    spy_price_prior: float = 0.0      # price at prior evaluation (for period return)
    inception_price: float = 0.0      # price at benchmark inception
    inception_date: Optional[date] = None

    # POSITION
    shares: float = 0.0               # benchmark shares held (buy-and-hold)
    cash: float = 0.0                 # residual cash (from fractional shares)

    # NAV ACCOUNTING
    inception_nav: float = 1_000_000.0
    starting_nav: float = 0.0         # NAV at start of this period
    ending_nav: float = 0.0           # NAV at close of this period

    # RETURNS
    period_return: float = 0.0        # return for this cycle period
    cumulative_return: float = 0.0    # cumulative return from inception
    max_drawdown: float = 0.0         # max drawdown from inception to this cycle

    # DATA PROVENANCE
    provider: str = "yahoo_finance"
    snapshot_fingerprint: str = ""
    pit_violation: bool = False        # True if price date > knowledge_as_of
    is_inception_cycle: bool = False   # True for the first (buy) cycle

    # OPERATIONS
    start_time: str = ""
    end_time: str = ""
    status: str = "PARTIAL"
    error_message: str = ""

    # IMMUTABILITY
    sealed_at: str = ""
    data_limitation: str = _BENCHMARK_DATA_LIMITATION

    # ── public API ────────────────────────────────────────────────────────────

    def seal(self, status: str = "SUCCESS") -> None:
        if not self.sealed_at:
            self.status = status
            self.sealed_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    @property
    def is_sealed(self) -> bool:
        return bool(self.sealed_at)

    def record_fingerprint(self) -> str:
        body = json.dumps({
            "cycle_id": self.cycle_id,
            "benchmark_symbol": self.benchmark_symbol,
            "spy_price": self.spy_price,
            "ending_nav": self.ending_nav,
            "status": self.status,
        }, sort_keys=True)
        return hashlib.blake2b(body.encode(), digest_size=16).hexdigest()

    def to_dict(self) -> dict:
        d: dict = {}
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            if isinstance(v, date) and not isinstance(v, datetime):
                d[f.name] = v.isoformat()
            else:
                d[f.name] = v
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BenchmarkCycleRecord":
        kw = {k: v for k, v in d.items()
              if k in {f.name for f in dataclasses.fields(cls)}}
        for dk in ("evaluation_date", "knowledge_as_of", "inception_date"):
            raw = kw.get(dk)
            if isinstance(raw, str) and raw:
                kw[dk] = date.fromisoformat(raw)
        return cls(**kw)


# ── benchmark ledger ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BenchmarkPerformanceSummary:
    """Computed benchmark statistics.  Mirrors ForwardPerformanceSummary shape."""
    n_cycles: int
    benchmark_symbol: str
    inception_date: Optional[date]
    inception_price: float
    inception_nav: float
    current_nav: float
    cumulative_return: float
    monthly_returns: list
    max_drawdown: float
    annualized_return: Optional[float]
    annualized_return_label: str     # "ESTIMATED" | "INSUFFICIENT_SAMPLE"
    volatility: Optional[float]
    volatility_label: str
    data_limitation: str


class BenchmarkLedger:
    """Read-only view of sealed benchmark cycle records.

    Reads from {campaign_dir}/benchmark/*.json.  Never writes.
    """

    _BENCHMARK_DIR = "benchmark"

    def __init__(self, campaign_dir: Path) -> None:
        self._bdir = campaign_dir / self._BENCHMARK_DIR

    def list_cycles(self) -> list[BenchmarkCycleRecord]:
        recs: list[BenchmarkCycleRecord] = []
        if not self._bdir.exists():
            return recs
        for p in sorted(self._bdir.glob("*.json")):
            try:
                recs.append(BenchmarkCycleRecord.from_dict(json.loads(p.read_text())))
            except Exception:
                continue
        recs.sort(key=lambda r: (r.evaluation_date or date.min))
        return recs

    def get_cycle(self, cycle_id: str) -> Optional[BenchmarkCycleRecord]:
        p = self._bdir / f"{cycle_id}.json"
        if not p.exists():
            return None
        try:
            return BenchmarkCycleRecord.from_dict(json.loads(p.read_text()))
        except Exception:
            return None

    def latest_cycle(self) -> Optional[BenchmarkCycleRecord]:
        cycles = [c for c in self.list_cycles() if c.status == "SUCCESS"]
        return cycles[-1] if cycles else None

    def current_nav(self) -> float:
        c = self.latest_cycle()
        return c.ending_nav if c else 0.0

    def performance_summary(self) -> BenchmarkPerformanceSummary:
        success = [c for c in self.list_cycles() if c.status == "SUCCESS"]
        nav_series = [c.ending_nav for c in success]
        monthly_returns: list[float] = []
        if len(nav_series) >= 2:
            monthly_returns = [
                (nav_series[i] - nav_series[i - 1]) / nav_series[i - 1]
                for i in range(1, len(nav_series))
                if nav_series[i - 1] > 0
            ]

        first = success[0] if success else None
        last = success[-1] if success else None
        inception_nav = first.inception_nav if first else 1_000_000.0
        current = last.ending_nav if last else inception_nav

        cum_return = (current / inception_nav - 1.0) if inception_nav > 0 else 0.0

        # max drawdown from inception
        mdd = 0.0
        if nav_series:
            peak = nav_series[0]
            for nav in nav_series:
                peak = max(peak, nav)
                dd = (peak - nav) / peak if peak > 0 else 0.0
                mdd = max(mdd, dd)

        # annualized return (need >= 12 cycles)
        import statistics
        if len(success) >= 12:
            ann = (1 + cum_return) ** (12 / len(success)) - 1
            ann_label = "ESTIMATED"
        else:
            ann = None
            ann_label = "INSUFFICIENT_SAMPLE"

        # volatility (need >= 2 monthly returns)
        if len(monthly_returns) >= 2:
            vol: Optional[float] = statistics.stdev(monthly_returns) * (12 ** 0.5)
            vol_label = "ESTIMATED"
        else:
            vol = None
            vol_label = "INSUFFICIENT_SAMPLE"

        return BenchmarkPerformanceSummary(
            n_cycles=len(success),
            benchmark_symbol=first.benchmark_symbol if first else _BENCHMARK_SYMBOL,
            inception_date=first.inception_date if first else None,
            inception_price=first.inception_price if first else 0.0,
            inception_nav=inception_nav,
            current_nav=current,
            cumulative_return=cum_return,
            monthly_returns=monthly_returns,
            max_drawdown=mdd,
            annualized_return=ann,
            annualized_return_label=ann_label,
            volatility=vol,
            volatility_label=vol_label,
            data_limitation=_BENCHMARK_DATA_LIMITATION,
        )


# ── benchmark portfolio ───────────────────────────────────────────────────────

class BenchmarkPortfolio:
    """Passive buy-and-hold SPY benchmark, sealed per forward cycle.

    Usage:
        bp = BenchmarkPortfolio(campaign_dir, inception_nav=1_000_000.0)

        # cycle 1 — inception (buy)
        rec = bp.evaluate(cycle_id, as_of=date(2026,8,13), spy_price=550.0,
                          campaign_id="...", provider_records=None)

        # cycle 2 — ongoing
        rec = bp.evaluate(cycle_id, as_of=date(2026,9,10), spy_price=560.0,
                          campaign_id="...")

    Records are written to {campaign_dir}/benchmark/{cycle_id}.json.
    Repeated calls for the same cycle_id return the existing sealed record.
    """

    _BENCHMARK_DIR = "benchmark"

    def __init__(self, campaign_dir: Path, inception_nav: float = 1_000_000.0) -> None:
        self._dir = campaign_dir / self._BENCHMARK_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._inception_nav = inception_nav
        self.ledger = BenchmarkLedger(campaign_dir)

    def evaluate(
        self,
        cycle_id: str,
        as_of: date,
        spy_price: float,
        *,
        campaign_id: str = "",
        evaluation_date: Optional[date] = None,
    ) -> BenchmarkCycleRecord:
        """Evaluate benchmark for one cycle.

        Idempotent: if a sealed record for cycle_id already exists, return it.

        Args:
            cycle_id: Matches the ForwardCycleRecord cycle_id.
            as_of: Knowledge date (PIT constraint: spy_price must be <= as_of).
            spy_price: SPY closing price at as_of.
            campaign_id: Owning campaign identifier.
            evaluation_date: Logical month date; defaults to as_of with day=1.
        """
        # idempotency
        existing = self._load_sealed(cycle_id)
        if existing is not None:
            return existing

        start_time = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        eval_date = evaluation_date or date(as_of.year, as_of.month, 1)

        # get prior cycle for starting_nav and prior price
        prior = self.ledger.latest_cycle()

        # determine shares and inception fields
        if prior is None:
            # inception cycle: buy with all capital
            is_inception = True
            shares = self._inception_nav / spy_price if spy_price > 0 else 0.0
            cash = self._inception_nav - shares * spy_price
            starting_nav = self._inception_nav
            inception_price = spy_price
            inception_date = as_of
            spy_price_prior = 0.0
        else:
            is_inception = False
            shares = prior.shares
            cash = prior.cash
            starting_nav = prior.ending_nav
            inception_price = prior.inception_price
            inception_date = prior.inception_date
            spy_price_prior = prior.spy_price

        ending_nav = shares * spy_price + cash

        # returns
        period_return = (
            (spy_price - spy_price_prior) / spy_price_prior
            if (not is_inception) and spy_price_prior > 0 else 0.0
        )
        cumulative_return = (
            (ending_nav - self._inception_nav) / self._inception_nav
            if self._inception_nav > 0 else 0.0
        )

        # max drawdown from inception (read all prior + this)
        all_navs = [c.ending_nav for c in self.ledger.list_cycles()
                    if c.status == "SUCCESS"]
        all_navs.append(ending_nav)
        mdd = 0.0
        peak = all_navs[0] if all_navs else ending_nav
        for nav in all_navs:
            peak = max(peak, nav)
            dd = (peak - nav) / peak if peak > 0 else 0.0
            mdd = max(mdd, dd)

        # build fingerprint from price + date
        snap_body = json.dumps(
            {"symbol": _BENCHMARK_SYMBOL, "price": spy_price, "as_of": as_of.isoformat()},
            sort_keys=True)
        snap_fp = hashlib.blake2b(snap_body.encode(), digest_size=16).hexdigest()

        rec = BenchmarkCycleRecord(
            cycle_id=cycle_id,
            benchmark_symbol=_BENCHMARK_SYMBOL,
            evaluation_date=eval_date,
            knowledge_as_of=as_of,
            campaign_id=campaign_id,
            spy_price=spy_price,
            spy_price_prior=spy_price_prior,
            inception_price=inception_price,
            inception_date=inception_date,
            shares=shares,
            cash=cash,
            inception_nav=self._inception_nav,
            starting_nav=starting_nav,
            ending_nav=ending_nav,
            period_return=period_return,
            cumulative_return=cumulative_return,
            max_drawdown=mdd,
            snapshot_fingerprint=snap_fp,
            is_inception_cycle=is_inception,
            start_time=start_time,
            end_time=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
        )
        rec.seal("SUCCESS")
        self._persist(rec)
        return rec

    def _load_sealed(self, cycle_id: str) -> Optional[BenchmarkCycleRecord]:
        p = self._dir / f"{cycle_id}.json"
        if not p.exists():
            return None
        try:
            r = BenchmarkCycleRecord.from_dict(json.loads(p.read_text()))
            return r if r.is_sealed else None
        except Exception:
            return None

    def _persist(self, rec: BenchmarkCycleRecord) -> None:
        target = self._dir / f"{rec.cycle_id}.json"
        if target.exists():
            return  # never overwrite a sealed record
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec.to_dict(), indent=2, default=str))
        tmp.rename(target)


# ── SPY price fetcher ─────────────────────────────────────────────────────────

def fetch_spy_price(as_of: date) -> Optional[float]:
    """Fetch SPY closing price for as_of using yfinance.

    Returns the last available close price on or before as_of.
    Returns None if the fetch fails or no data is available.

    PIT constraint: only prices <= as_of are considered.
    This function must never be called with a future date.
    """
    try:
        import yfinance as yf  # type: ignore[import]
        from datetime import timedelta
        end = as_of + timedelta(days=1)
        start = as_of - timedelta(days=10)
        ticker = yf.Ticker(_BENCHMARK_SYMBOL)
        df = ticker.history(start=start.isoformat(), end=end.isoformat(),
                            auto_adjust=False)
        if df is None or df.empty:
            return None
        # use raw Close (not Adj Close) to avoid retroactive adjustments
        df = df[df.index.date <= as_of]  # type: ignore[attr-defined]
        if df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception:
        return None
