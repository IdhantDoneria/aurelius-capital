"""Price sources, panel construction, eligibility, and quality gates.

Numeric core is float64 pandas/numpy throughout (house convention: `Decimal` is
used only at the broker boundary in `execution.py`, never here).

ADJUSTMENT HONESTY (known, unverified assumption — state this in every module
that touches `close`): every row in `ohlcv` has `adjustment_factor = 1.0` and
`quality_score IS NULL`. The upstream fetch requested split/dividend-adjusted
prices (`yfinance auto_adjust=True`, `alpaca adjustment="all"`), so `close` is
*believed* to already be adjusted — but the `adjustment_factor` column that
would prove it was never populated. Treat every return computed from `close`
as provisionally trustworthy, not confirmed. Do not silently assume otherwise.

TIMEZONE: `ohlcv.timestamp` is `TIMESTAMPTZ`, stored in UTC, but duckdb-python
returns it tz-aware in the *session's* timezone (observed: Asia/Kolkata on this
host — not to be assumed elsewhere). Getting the conversion order wrong shifts
every bar onto the wrong calendar day on any host whose local offset straddles
midnight relative to UTC, which silently corrupts every downstream signal. Two
independent fixes are applied, belt and suspenders: (1) every DuckDB connection
pins `SET TimeZone = 'UTC'` immediately after opening, so SQL-side date/range
comparisons are unambiguous regardless of host locale; (2) `_to_utc_naive_date`
still explicitly converts to UTC before stripping tz info and flooring to
midnight, so the fix holds even if a future caller queries without going
through `DuckDBSource._connect`.

SCOPE: this is a US equity programme. Every DuckDB query filters to
`frequency='1d'` and drops three groups of rows, all verified against the live
store on 2026-08-22:

  - `source = 'nse_bhavcopy'` — 3,767 India symbols, out of scope.
  - `symbol LIKE 'CIK%'` — the whole `alpaca_iex` source, 6,162 "symbols" and
    7.38M rows, turns out to be keyed by SEC CIK identifiers (`CIK0000001750`)
    rather than by ticker. There is no CIK-to-ticker map anywhere in this
    repository, so those rows cannot be mapped onto tradable instruments. They
    are excluded rather than silently polluting the universe.
  - `symbol LIKE '%.NS'` — India again, belt and braces, since a handful of
    `.NS` tickers also arrived through the `csv` source.

What survives is the `csv` source: 2,143 symbols, of which 1,016 are US and
**410** clear both the three-year history requirement and the $3m median daily
dollar-volume floor. The specification's own study used 657 tickers with a
median of 593 eligible on any given day. Running 410 is a real deviation and it
matters: the specification's universe-shrinkage stress (Table 17) shows that a
smaller universe RAISES return and WORSENS drawdown, because the book gets more
concentrated. Expect that direction, and see the build report for the
remediation (a point-in-time vendor feed, which also fixes survivorship).

BENCHMARK: the store contains no index instrument at all — no SPY, IVV, VOO,
QQQ, DIA, IWM or ^GSPC, under any source. The programme's entire directional
layer (four of ten sleeves, carrying `k_core = 4.00`) trades the benchmark, so
without it the programme cannot run. `CompositeSource` therefore fetches the
universe from DuckDB and falls through to Yahoo for whatever is missing,
caching to parquet so a second run is offline. A missing benchmark raises;
nothing substitutes a proxy silently.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import Protocol

import duckdb
import numpy as np
import pandas as pd

from mentisrex.core.logging import get_logger
from mentisrex.infrastructure.config.settings import get_settings
from mentisrex.market_data.adapters.base import RawBar
from mentisrex.market_data.adapters.yahoo import YahooFinanceAdapter
from mentisrex.programme.config import (
    DataQualityError,
    ProgrammeConfig,
    ProgrammeError,
    UniverseConfig,
)

logger = get_logger(__name__)

_OHLCV_FIELDS = ("open", "high", "low", "close", "volume")

# One definition, used by every DuckDB query in this module, so the row filter
# and the universe-inventory query can never drift apart. See the SCOPE section
# of the module docstring for what each clause removes and why.
_SOURCE_FILTER_SQL = """
    frequency = '1d'
    AND source != 'nse_bhavcopy'
    AND symbol NOT LIKE 'CIK%'
    AND symbol NOT LIKE '%.NS'
"""


# ── Panel ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PricePanel:
    """Aligned OHLCV panel for a universe plus one benchmark.

    Frozen because a panel handed to a signal function must never be mutated in
    place; `truncate()` returns a brand-new panel rather than slicing this one.

    `returns` and `dollar_volume` are cached with `functools.cached_property`.
    That descriptor writes its result straight into `instance.__dict__`, which
    bypasses the frozen dataclass's `__setattr__` override entirely — it never
    calls `setattr()`. The only requirement is that instances keep a `__dict__`,
    which the default `@dataclass(frozen=True)` (no `slots=True`) already
    provides. No `eq=False` or manual cache plumbing needed; `truncate()`
    getting a fresh instance is exactly what makes the cache invalidation free
    too, since a new object's `__dict__` starts empty.
    """

    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    close: pd.DataFrame  # believed split/dividend adjusted — see module docstring
    volume: pd.DataFrame
    benchmark: str

    @property
    def columns(self) -> pd.Index:
        """Universe tickers sorted ascending, then the benchmark ticker last."""
        cols = list(self.close.columns)
        universe = sorted(c for c in cols if c != self.benchmark)
        if self.benchmark in cols:
            return pd.Index([*universe, self.benchmark])
        return pd.Index(universe)

    @property
    def index(self) -> pd.DatetimeIndex:
        return self.close.index

    @cached_property
    def returns(self) -> pd.DataFrame:
        return self.close.pct_change()

    @cached_property
    def dollar_volume(self) -> pd.DataFrame:
        return self.close * self.volume

    @property
    def benchmark_close(self) -> pd.Series:
        return self.close[self.benchmark]

    @property
    def benchmark_returns(self) -> pd.Series:
        return self.returns[self.benchmark]

    def universe_columns(self) -> pd.Index:
        return pd.Index([c for c in self.columns if c != self.benchmark])

    def truncate(self, end: pd.Timestamp) -> PricePanel:
        """Panel sliced to `index <= end`. Used by `test_no_lookahead_signals`."""
        end_ts = pd.Timestamp(end)
        kept = self.index[self.index <= end_ts]
        return PricePanel(
            open=self.open.loc[kept],
            high=self.high.loc[kept],
            low=self.low.loc[kept],
            close=self.close.loc[kept],
            volume=self.volume.loc[kept],
            benchmark=self.benchmark,
        )


class PriceSource(Protocol):
    def fetch(self, tickers: list[str], start: str, end: str) -> PricePanel: ...

    def fetch_long(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        """Raw long frame: symbol, timestamp, open, high, low, close, volume.

        Exists so `CompositeSource` can stitch several sources together before a
        panel is built. `fetch` cannot serve that purpose because building a
        panel requires the benchmark, and the source that holds the universe is
        not necessarily the source that holds the benchmark. An empty frame
        means "I have none of these", which is a normal answer here, not an
        error.
        """
        ...


# ── Shared helpers ──────────────────────────────────────────────────────────


def _to_utc_naive_date(ts: pd.Series) -> pd.Series:
    """Normalise a timestamp column to tz-naive UTC dates (floored to midnight).

    See the module docstring's TIMEZONE section: converting to UTC *before*
    dropping tz info is the only safe order.

    Accepts a column that is not yet datetimelike. That happens for real when
    `CompositeSource` concatenates a tz-aware DuckDB frame with a tz-naive
    parquet frame — pandas widens the result to `object`, and the `.dt`
    accessor then refuses to work at all. Coercing first, with `utc=True` so
    mixed offsets collapse onto one timeline, is what keeps that stitch safe.
    """
    if not pd.api.types.is_datetime64_any_dtype(ts):
        ts = pd.to_datetime(ts, utc=True, errors="coerce")
    if ts.dt.tz is None:
        return ts.dt.normalize()
    return ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()


def _panel_from_long(raw: pd.DataFrame, benchmark: str) -> PricePanel:
    """Pivot a long (symbol, timestamp, open, high, low, close, volume) frame
    into a PricePanel.

    Per ADDENDUM A.4, there is no calendar library in this project and the
    programme's trading calendar is simply the set of dates the benchmark has a
    bar. So the panel's row index is fixed to exactly those dates — every other
    symbol is reindexed onto it, which is a `NaN` (not a KeyError) wherever a
    name has no bar on a benchmark trading day.
    """
    if raw.empty:
        raise DataQualityError(
            "no OHLCV rows returned for the requested tickers/date range",
            detail="check the symbol list, date range, and that frequency='1d' rows exist",
        )
    raw = raw.copy()
    raw["timestamp"] = _to_utc_naive_date(raw["timestamp"])
    # (symbol, timestamp, frequency) is the table's primary key, so duplicates
    # after date-normalisation shouldn't occur for real data; this guard is a
    # defensive no-op that keeps pivot() from raising if they ever do.
    raw = raw.drop_duplicates(subset=["symbol", "timestamp"], keep="last")

    bench_dates = raw.loc[raw["symbol"] == benchmark, "timestamp"]
    if bench_dates.empty:
        raise DataQualityError(
            f"benchmark {benchmark!r} has no bars for the requested range",
            detail=(
                "PricePanel.index is defined as the benchmark's own bar dates "
                "(ADDENDUM A.4) — without benchmark data there is no calendar to "
                "build the panel against"
            ),
        )
    calendar = pd.DatetimeIndex(sorted(bench_dates.unique()))

    fields: dict[str, pd.DataFrame] = {}
    for field in _OHLCV_FIELDS:
        wide = raw.pivot(index="timestamp", columns="symbol", values=field)
        fields[field] = wide.reindex(index=calendar).sort_index(axis=1).astype("float64")

    return PricePanel(
        open=fields["open"],
        high=fields["high"],
        low=fields["low"],
        close=fields["close"],
        volume=fields["volume"],
        benchmark=benchmark,
    )


def _last_valid_gap(frame: pd.DataFrame) -> pd.DataFrame:
    """Row-position gap since each column's last non-null value.

    0 on a row whose own value is non-null; NaN where no valid value has been
    observed yet. Strictly causal (uses only the current row and earlier ones),
    which is what keeps `eligibility_mask` and `quality_gate` look-ahead free.
    "Row position" is exactly ADDENDUM A.4's definition of a business day —
    a position in `panel.index`, not a `pd.bdate_range` slot.
    """
    row_num = pd.DataFrame(
        np.broadcast_to(np.arange(len(frame.index))[:, None], frame.shape).astype("float64"),
        index=frame.index,
        columns=frame.columns,
    )
    last_valid_row = row_num.where(frame.notna()).ffill()
    return row_num - last_valid_row


# ── Sources ───────────────────────────────────────────────────────────────────


class DuckDBSource:
    """PRIMARY source. Reads the `ohlcv` table from analytics.duckdb, read-only.

    Filters to `frequency='1d'` and excludes `source='nse_bhavcopy'` (India, out
    of scope). Opened read-only because this database is shared with the rest
    of the platform and must not be locked or mutated by the programme.
    """

    def __init__(self, db_path: str | None = None, benchmark: str = "SPY") -> None:
        self.db_path = db_path or get_settings().duckdb_path
        self.benchmark = benchmark.upper()

    @contextmanager
    def _connect(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        conn = duckdb.connect(self.db_path, read_only=True)
        try:
            # Pin the session to UTC so every timestamp comparison and cast
            # below is unambiguous regardless of the host's local timezone —
            # see the module docstring's TIMEZONE section.
            conn.execute("SET TimeZone = 'UTC'")
            yield conn
        finally:
            conn.close()

    def fetch_long(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        symbols = sorted({t.upper() for t in tickers})
        if not symbols:
            return pd.DataFrame(columns=["symbol", "timestamp", *_OHLCV_FIELDS])
        placeholders = ", ".join("?" for _ in symbols)
        sql = f"""
            SELECT symbol, timestamp, open, high, low, close, volume
            FROM ohlcv
            WHERE {_SOURCE_FILTER_SQL}
              AND symbol IN ({placeholders})
              AND timestamp >= ? AND timestamp <= ?
            ORDER BY symbol, timestamp
        """
        with self._connect() as conn:
            raw = conn.execute(sql, [*symbols, start, end]).fetchdf()
        logger.info(
            "duckdb_source_fetch",
            n_symbols=len(symbols),
            n_rows=len(raw),
            start=start,
            end=end,
        )
        return raw

    def fetch(self, tickers: list[str], start: str, end: str) -> PricePanel:
        symbols = sorted({t.upper() for t in tickers} | {self.benchmark})
        return _panel_from_long(self.fetch_long(symbols, start, end), self.benchmark)

    def available_symbols(self, min_bars: int = 252) -> pd.DataFrame:
        """symbol, n_bars, first_date, last_date, median_dollar_volume.

        Aggregated entirely in SQL (feeds `cli universe`, which needs this over
        the full ~12k-symbol table — doing it in pandas would mean pulling every
        row across the wire first).
        """
        sql = f"""
            SELECT
                symbol,
                COUNT(*) AS n_bars,
                MIN(timestamp) AS first_date,
                MAX(timestamp) AS last_date,
                MEDIAN(CAST(close AS DOUBLE) * CAST(volume AS DOUBLE)) AS median_dollar_volume
            FROM ohlcv
            WHERE {_SOURCE_FILTER_SQL}
            GROUP BY symbol
            HAVING COUNT(*) >= ?
            ORDER BY median_dollar_volume DESC
        """
        with self._connect() as conn:
            df = conn.execute(sql, [min_bars]).fetchdf()
        for col in ("first_date", "last_date"):
            df[col] = _to_utc_naive_date(df[col])
        return df


class ParquetSource:
    """Secondary / offline cache. Reads `data_dir/ohlcv/{ticker}.parquet`.

    Expected schema per file: `DatetimeIndex` named "timestamp" (tz-naive,
    normalised to midnight) with columns open, high, low, close, volume. This
    is exactly what `YahooSource` writes, so the two are interchangeable for a
    second, offline run.
    """

    def __init__(self, data_dir: str, benchmark: str = "SPY") -> None:
        self.data_dir = Path(data_dir)
        self.benchmark = benchmark.upper()

    def _path(self, ticker: str) -> Path:
        return self.data_dir / "ohlcv" / f"{ticker.upper()}.parquet"

    def fetch_long(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        symbols = sorted({t.upper() for t in tickers})
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        frames: list[pd.DataFrame] = []
        missing: list[str] = []
        for sym in symbols:
            path = self._path(sym)
            if not path.exists():
                missing.append(sym)
                continue
            df = pd.read_parquet(path)
            df = df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
            df = df.reset_index().rename(columns={df.index.name or "index": "timestamp"})
            df["symbol"] = sym
            frames.append(df)
        if missing:
            logger.info("parquet_source_missing_symbols", n_missing=len(missing))
        if not frames:
            return pd.DataFrame(columns=["symbol", "timestamp", *_OHLCV_FIELDS])
        return pd.concat(frames, ignore_index=True)

    def fetch(self, tickers: list[str], start: str, end: str) -> PricePanel:
        symbols = sorted({t.upper() for t in tickers} | {self.benchmark})
        raw = self.fetch_long(symbols, start, end)
        if raw.empty:
            raise DataQualityError(
                f"no parquet files found under {self.data_dir / 'ohlcv'} for the requested symbols"
            )
        return _panel_from_long(raw, self.benchmark)


class YahooSource:
    """Top-up source for symbols missing from DuckDB.

    Wraps the existing `mentisrex.market_data` Yahoo adapter and writes through
    to `ParquetSource`'s layout, so a second run over the same range is fully
    offline.
    """

    def __init__(self, data_dir: str, benchmark: str = "SPY") -> None:
        self.data_dir = Path(data_dir)
        self.benchmark = benchmark.upper()
        self._parquet = ParquetSource(data_dir, self.benchmark)
        self._adapter = YahooFinanceAdapter()

    def fetch_long(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        import asyncio

        symbols = sorted({t.upper() for t in tickers})
        if not symbols:
            return pd.DataFrame(columns=["symbol", "timestamp", *_OHLCV_FIELDS])
        start_dt = datetime.fromisoformat(start).replace(tzinfo=UTC)
        end_dt = datetime.fromisoformat(end).replace(tzinfo=UTC)

        async def _fetch_all() -> list[list[RawBar] | BaseException]:
            return await asyncio.gather(
                *(self._adapter.fetch_ohlcv(sym, start_dt, end_dt, "1d") for sym in symbols),
                return_exceptions=True,
            )

        results = asyncio.run(_fetch_all())
        failed = 0
        for sym, bars in zip(symbols, results, strict=True):
            if isinstance(bars, BaseException):
                failed += 1
                logger.warning("yahoo_source_fetch_failed", symbol=sym, error=str(bars))
                continue
            self._write_parquet(sym, bars)
        logger.info("yahoo_source_fetch", n_requested=len(symbols), n_failed=failed)
        return self._parquet.fetch_long(symbols, start, end)

    def fetch(self, tickers: list[str], start: str, end: str) -> PricePanel:
        symbols = sorted({t.upper() for t in tickers} | {self.benchmark})
        return _panel_from_long(self.fetch_long(symbols, start, end), self.benchmark)

    def _write_parquet(self, symbol: str, bars: list[RawBar]) -> None:
        if not bars:
            return
        df = (
            pd.DataFrame(
                {
                    "timestamp": _to_utc_naive_date(
                        pd.Series([pd.Timestamp(b.timestamp) for b in bars])
                    ),
                    "open": [float(b.open) for b in bars],
                    "high": [float(b.high) for b in bars],
                    "low": [float(b.low) for b in bars],
                    "close": [float(b.close) for b in bars],
                    "volume": [float(b.volume) for b in bars],
                }
            )
            .set_index("timestamp")
            .sort_index()
        )

        path = self._parquet._path(symbol)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            df = pd.concat([pd.read_parquet(path), df])
            df = df[~df.index.duplicated(keep="last")].sort_index()
        df.to_parquet(path)


class CompositeSource:
    """Try each source in order, per symbol, and stitch the results together.

    This exists because of a hard fact about the platform's store: it holds the
    single-name universe but carries no index instrument at all. The
    programme's directional layer is four of its ten sleeves and it trades
    nothing but the benchmark, so a source that cannot supply the benchmark
    cannot supply the programme on its own.

    The first source is asked for everything. Each later source is asked only
    for what is still missing, so a slow network source is never queried for
    symbols already held locally. A symbol absent from every source is dropped
    with a single aggregate warning rather than one line per name.

    A missing BENCHMARK is fatal. Nothing here substitutes a proxy: a book whose
    benchmark silently became a different instrument is running a bet nobody
    chose.
    """

    def __init__(self, sources: Sequence[PriceSource], benchmark: str = "SPY") -> None:
        if not sources:
            raise ProgrammeError("CompositeSource requires at least one source")
        self.sources = list(sources)
        self.benchmark = benchmark.upper()

    def fetch_long(self, tickers: list[str], start: str, end: str) -> pd.DataFrame:
        wanted = sorted({t.upper() for t in tickers} | {self.benchmark})
        collected: list[pd.DataFrame] = []
        outstanding = list(wanted)

        for source in self.sources:
            if not outstanding:
                break
            try:
                raw = source.fetch_long(outstanding, start, end)
            except Exception as exc:  # a source that fails is skipped, not fatal
                logger.warning(
                    "composite_source_failed",
                    source=type(source).__name__,
                    error=str(exc),
                )
                continue
            if raw is None or raw.empty:
                continue
            found = {str(s).upper() for s in raw["symbol"].unique()}
            # Normalise per-source, before the concat. DuckDB hands back
            # tz-aware timestamps and parquet hands back tz-naive ones; letting
            # those meet in a single concat widens the column to `object` and
            # loses the datetime dtype for everything downstream.
            raw = raw.copy()
            raw["timestamp"] = _to_utc_naive_date(raw["timestamp"])
            collected.append(raw)
            outstanding = [s for s in outstanding if s not in found]

        if outstanding:
            logger.warning(
                "composite_source_symbols_unavailable",
                n_missing=len(outstanding),
                n_requested=len(wanted),
                sample=outstanding[:10],
            )
        if self.benchmark in outstanding:
            raise DataQualityError(
                f"benchmark {self.benchmark!r} unavailable from every configured source",
                detail=(
                    "the DuckDB store contains no index instrument; the fallback "
                    "source (Yahoo) must be reachable at least once so the "
                    "benchmark can be cached to parquet"
                ),
            )
        if not collected:
            return pd.DataFrame(columns=["symbol", "timestamp", *_OHLCV_FIELDS])
        return pd.concat(collected, ignore_index=True)

    def fetch(self, tickers: list[str], start: str, end: str) -> PricePanel:
        return _panel_from_long(self.fetch_long(tickers, start, end), self.benchmark)


class PointInTimeSource:
    """STUB. Point-in-time universe membership with delisting returns.

    Every other source in this module is survivor-biased: DuckDBSource (and the
    ingestion feeding it) only ever wrote bars for tickers that are live today,
    so a name that was removed from the index — bankruptcy, buyout, delisting —
    simply has no rows. Spec §7.5 estimates 0.5-1.5 points/year of annual-return
    overstatement in the satellite (cross-sectional) sleeves from this bias, up
    to 3.2 points of CAGR in the stress case (§11.1's claims, not this module's).

    Fixing it needs point-in-time index membership plus delisting returns, which
    requires Norgate Premium Data, Sharadar (via Nasdaq Data Link), or a CRSP
    academic subscription — spec §7.5 prices this at about $500/year and calls
    it "the highest-value expenditure available to this programme." Until one of
    those three is subscribed to and `fetch()` implemented against it, this
    class refuses to run rather than fake point-in-time correctness.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(
            "PointInTimeSource needs a point-in-time universe + delisting-return "
            "data subscription (Norgate Premium Data, Sharadar via Nasdaq Data Link, "
            "or a CRSP academic subscription — spec §7.5, ~$500/year). None is "
            "configured. Do not fake point-in-time membership or delisting returns: "
            "subscribe to one of the three and implement fetch() against it."
        )

    def fetch(self, tickers: list[str], start: str, end: str) -> PricePanel:
        raise NotImplementedError("see __init__")


# ── Universe / panel construction ──────────────────────────────────────────────


def load_universe(path: str) -> list[str]:
    """One ticker per line; `#` starts a comment; blank lines ignored."""
    p = Path(path)
    if not p.exists():
        raise ProgrammeError(
            f"universe file not found: {path}",
            detail="run `python -m mentisrex.programme.cli universe` to generate it",
        )
    tickers: list[str] = []
    for raw_line in p.read_text().splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line:
            tickers.append(line.upper())
    return tickers


def default_source(config: ProgrammeConfig, db_path: str | None = None) -> PriceSource:
    """The source the programme uses unless a caller supplies its own.

    DuckDB for the universe, Yahoo for whatever DuckDB does not have — which in
    practice means the benchmark, since the store carries no index instrument.
    Yahoo writes through to parquet under `config.data_dir`, so the second run
    over the same range needs no network.
    """
    bench = config.universe.benchmark
    return CompositeSource(
        [DuckDBSource(db_path, bench), YahooSource(config.data_dir, bench)],
        benchmark=bench,
    )


def build_panel(
    config: ProgrammeConfig,
    source: PriceSource | None = None,
    start: str = "2017-01-01",
    end: str | None = None,
    db_path: str | None = None,
) -> PricePanel:
    """Load the universe ticker list and fetch the aligned panel.

    `source=None` assembles `default_source(...)`. An explicitly supplied source
    is always honoured, which is how the test suite feeds a synthetic panel in
    without touching a database or the network.
    """
    tickers = load_universe(config.universe.tickers_file)
    end = end or datetime.now(UTC).date().isoformat()
    src = source if source is not None else default_source(config, db_path)
    logger.info(
        "programme_build_panel",
        n_tickers=len(tickers),
        start=start,
        end=end,
        source=type(src).__name__,
    )
    return src.fetch(tickers, start, end)


def eligibility_mask(panel: PricePanel, config: UniverseConfig) -> pd.DataFrame:
    """bool frame over `panel.universe_columns()`.

    A name is eligible on date t iff, using data through t only:
      - >= min_history_days non-null closes so far
      - 21-day median dollar volume >= min_dollar_volume (spec §5.1)
      - close >= min_price
      - last non-null close within max_staleness_days business days of t

    Every statistic below is an expanding/rolling/forward-filled computation
    over rows `<= t`, so truncating the panel and recomputing reproduces the
    retained values exactly — this is what `test_no_lookahead_signals` checks.
    The benchmark is never a column of the returned frame.
    """
    cols = panel.universe_columns()
    closes = panel.close[cols]
    dollar_vol = panel.dollar_volume[cols]

    n_history = closes.notna().cumsum()
    median_dv = dollar_vol.rolling(21, min_periods=21).median()
    staleness_days = _last_valid_gap(closes)

    eligible = (
        (n_history >= config.min_history_days)
        & (median_dv >= config.min_dollar_volume)
        & (closes >= config.min_price)
        & (staleness_days <= config.max_staleness_days)
    )
    return eligible.fillna(False)


# ── Quality gate ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QualityReport:
    as_of: pd.Timestamp
    fatal: tuple[str, ...]  # empty => OK to trade
    warnings: tuple[str, ...]
    n_eligible: int
    staleness_days: int
    missing_fraction: float

    @property
    def ok(self) -> bool:
        return not self.fatal


def quality_gate(
    panel: PricePanel,
    mask: pd.DataFrame,
    config: ProgrammeConfig,
    as_of: pd.Timestamp | None = None,
) -> QualityReport:
    """Four FATAL conditions (spec Table 15 / §14.2 09:15 quality gate):

      STALE_PANEL       last bar > max_staleness_days business days old
      MISSING_SYMBOLS   > 35% of requested symbols have no bar on as_of
      BENCHMARK_GAP     benchmark close missing or non-positive on as_of
      UNIVERSE_COLLAPSE eligible count < min_eligible_names

    Warnings: any single-name gap > 5 business days; any |daily return| > 50%.
    """
    as_of_ts = (
        pd.Timestamp(as_of).normalize() if as_of is not None else pd.Timestamp.now().normalize()
    )

    covered = panel.index[panel.index <= as_of_ts]
    if len(covered) == 0:
        # Panel has no data at or before as_of at all — maximally stale.
        staleness_days = 10**9
        eval_ts = as_of_ts
    else:
        last_bar = covered[-1]
        # Two DIFFERENT dates, and conflating them is the bug this separation
        # exists to prevent. `as_of_ts` is the instant the gate is being run —
        # normally wall-clock now — and is used for one thing only: measuring
        # how old the panel is. `eval_ts` is the most recent bar the panel
        # actually has, and every content check below is performed against it.
        # Evaluating content on a date the panel does not contain reports
        # "100% of symbols missing" for a perfectly healthy panel, which is
        # both wrong and exactly the kind of false alarm that trains an
        # operator to ignore the gate.
        eval_ts = last_bar
        # ponytail: staleness of the whole panel vs. an external `as_of` is
        # measured in raw calendar days, not "business days" in the strict
        # ADDENDUM A.4 sense — there is no calendar library to project
        # panel.index forward past its own last entry, so we cannot count
        # index positions between the panel's last bar and a date it doesn't
        # contain. The row-position definition IS used below (via
        # _last_valid_gap) for single-name gaps and MISSING_SYMBOLS, where
        # both endpoints are inside panel.index and unambiguous. Upgrade this
        # if a real trading-calendar dependency is ever added.
        staleness_days = (as_of_ts - last_bar).days

    fatal: list[str] = []
    if staleness_days > config.universe.max_staleness_days:
        fatal.append("STALE_PANEL")

    universe_cols = panel.universe_columns()
    if eval_ts in panel.close.index:
        missing_fraction = float(panel.close.loc[eval_ts, universe_cols].isna().mean())
    else:
        missing_fraction = 1.0
    if missing_fraction > 0.35:
        fatal.append("MISSING_SYMBOLS")

    if eval_ts in panel.close.index:
        bench_val = panel.close.loc[eval_ts, panel.benchmark]
        benchmark_gap = pd.isna(bench_val) or bench_val <= 0
    else:
        benchmark_gap = True
    if benchmark_gap:
        fatal.append("BENCHMARK_GAP")

    n_eligible = int(mask.loc[eval_ts].sum()) if eval_ts in mask.index else 0
    if n_eligible < config.universe.min_eligible_names:
        fatal.append("UNIVERSE_COLLAPSE")

    warnings: list[str] = []
    gap = _last_valid_gap(panel.close[universe_cols])
    if eval_ts in gap.index:
        stale_names = gap.loc[eval_ts][gap.loc[eval_ts] > 5]
        warnings.extend(
            f"SINGLE_NAME_GAP {sym}: {int(days)} business days since last bar"
            for sym, days in stale_names.items()
        )
    if eval_ts in panel.returns.index:
        moves = panel.returns.loc[eval_ts]
        big_moves = moves[moves.abs() > 0.50]
        warnings.extend(
            f"LARGE_MOVE {sym}: {ret:+.1%} on {eval_ts.date()}" for sym, ret in big_moves.items()
        )

    logger.info(
        "programme_quality_gate",
        as_of=str(as_of_ts.date()),
        fatal=list(fatal),
        n_warnings=len(warnings),
        n_eligible=n_eligible,
        staleness_days=staleness_days,
        missing_fraction=missing_fraction,
    )

    return QualityReport(
        as_of=as_of_ts,
        fatal=tuple(fatal),
        warnings=tuple(warnings),
        n_eligible=n_eligible,
        staleness_days=int(staleness_days),
        missing_fraction=missing_fraction,
    )
