"""Policy-rate path for the financing model (spec section 2.3).

`r` in the daily financing-drag formula (spec §2.3, Table 8) is the US
**effective federal funds rate**, expressed as a decimal (5.33% -> 0.0533).
`allocator.financing_cost()` consumes the series this module produces.

Source of the hard-coded schedule in `embedded_policy_rates()`: FOMC target-range
decisions (each a (lower, upper) percent pair), effective the first business day
after the announcement, matching how FRED's daily effective-rate series (DFF)
actually steps. The rate used for each step is the **midpoint of the target
range**, per this module's contract, not the realised effective rate (which
drifts a few bp inside the range) — spec §2.3 approximates `r` this way for the
financing model. Schedule as-of / last verified: 2026-08-22.

Everything through the 2023-07-27 hike (5.25-5.50% range) is well inside this
model's training data and stated from confident recall. The 2024 cuts
(Sep/Nov/Dec 2024) and the 2025 cuts (Sep/Oct/Dec 2025) sit at or past this
model's actual knowledge cutoff (Jan 2026); those dates and the "held at
3.50-3.75% through Jul 2026" tail were checked via a live web search run at
authoring time (fedprimerate.com FOMC history table, corroborated by press
coverage of the Apr/Jun/Jul 2026 FOMC meetings) rather than recalled — see the
`# CONTRACT-NOTE:` markers below on the entries this applies to. Any step dated
after this model's Jan 2026 knowledge cutoff is therefore a **verified-at-build-
time lookup, not a trained-in observation**, and should be re-checked against
FRED DFF before being trusted for a live run past this file's as-of date.
"""

from __future__ import annotations

import io
import urllib.request
from datetime import UTC, datetime

import pandas as pd

from mentisrex.core.logging import get_logger
from mentisrex.programme.config import ConfigError

logger = get_logger(__name__)

try:
    import httpx
except ImportError:  # pragma: no cover - httpx is a declared runtime dependency
    httpx = None  # type: ignore[assignment]

_FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF"

# Effective date (day the new rate applies, i.e. the FOMC announcement date + 1
# business day, matching FRED DFF) -> effective federal funds rate as a decimal,
# taken as the midpoint of the announced target range. Covers 2015-01-01 to
# present per contract; forward-filled to a daily index by embedded_policy_rates().
_SCHEDULE: tuple[tuple[str, float], ...] = (
    ("2015-01-01", 0.00125),  # ZIRP tail: target range 0.00-0.25%, midpoint used
    ("2015-12-17", 0.00375),  # -> 0.25-0.50%
    ("2016-12-15", 0.00625),  # -> 0.50-0.75%
    ("2017-03-16", 0.00875),  # -> 0.75-1.00%
    ("2017-06-15", 0.01125),  # -> 1.00-1.25%
    ("2017-12-14", 0.01375),  # -> 1.25-1.50%
    ("2018-03-22", 0.01625),  # -> 1.50-1.75%
    ("2018-06-14", 0.01875),  # -> 1.75-2.00%
    ("2018-09-27", 0.02125),  # -> 2.00-2.25%
    ("2018-12-20", 0.02375),  # -> 2.25-2.50%  cycle peak
    ("2019-08-01", 0.02125),  # -> 2.00-2.25%  first 2019 "mid-cycle" cut
    ("2019-09-19", 0.01875),  # -> 1.75-2.00%
    ("2019-10-31", 0.01625),  # -> 1.50-1.75%
    ("2020-03-04", 0.01125),  # -> 1.00-1.25%  emergency intermeeting COVID cut
    ("2020-03-16", 0.00125),  # -> 0.00-0.25%  emergency cut to the zero floor
    ("2022-03-17", 0.00375),  # -> 0.25-0.50%  hiking cycle begins
    ("2022-05-05", 0.00875),  # -> 0.75-1.00%  50bp
    ("2022-06-16", 0.01625),  # -> 1.50-1.75%  75bp
    ("2022-07-28", 0.02375),  # -> 2.25-2.50%  75bp
    ("2022-09-22", 0.03125),  # -> 3.00-3.25%  75bp
    ("2022-11-03", 0.03875),  # -> 3.75-4.00%  75bp
    ("2022-12-15", 0.04375),  # -> 4.25-4.50%  50bp
    ("2023-02-02", 0.04625),  # -> 4.50-4.75%  25bp
    ("2023-03-23", 0.04875),  # -> 4.75-5.00%  25bp
    ("2023-05-04", 0.05125),  # -> 5.00-5.25%  25bp
    ("2023-07-27", 0.05375),  # -> 5.25-5.50%  25bp, cycle peak, held ~13 months
    # CONTRACT-NOTE: the four entries below (2024-09 through 2025-12) postdate
    # this model's confident trained-in recall. They were checked via a live
    # WebSearch/WebFetch against fedprimerate.com's FOMC history table during
    # authoring (session date 2026-08-22), not recalled from training. Re-verify
    # against FRED DFF/FEDFUNDS before relying on them for a live run.
    ("2024-09-19", 0.04875),  # -> 4.75-5.00%  50bp, first cut of the 2024 cycle
    ("2024-11-08", 0.04625),  # -> 4.50-4.75%  25bp
    ("2024-12-19", 0.04375),  # -> 4.25-4.50%  25bp
    # CONTRACT-NOTE: entries below are fully past this model's Jan 2026 training
    # cutoff. Sourced the same way (live web search at authoring time, same
    # source), not trained-in. Treat as an assumption to be reconfirmed against
    # FRED, not an observation.
    ("2025-09-18", 0.04125),  # -> 4.00-4.25%  25bp
    ("2025-10-30", 0.03875),  # -> 3.75-4.00%  25bp
    ("2025-12-11", 0.03625),  # -> 3.50-3.75%  25bp; held here through the most
    # recent verified FOMC decision (2026-07-29, "hold at 3.50-3.75%") as of
    # this file's as-of date above.
)


def embedded_policy_rates() -> pd.Series:
    """Hard-coded effective Fed Funds step schedule, forward-filled to daily.

    Returns a `pd.Series` of the rate as a decimal (0.0533 == 5.33%) on a
    tz-naive `DatetimeIndex` covering 2015-01-01 through today, so backtests are
    reproducible offline without a network call (spec Table 26: "embedded path
    for reproducibility"). See the module docstring for source and as-of date,
    and the `# CONTRACT-NOTE:` comments on `_SCHEDULE` for which steps are
    trained-in recall versus a build-time web lookup.
    """
    today = pd.Timestamp(datetime.now(UTC).date())
    index = pd.date_range("2015-01-01", today, freq="D")
    series = pd.Series(index=index, dtype="float64", name="policy_rate")
    for effective_date, rate in _SCHEDULE:
        series.loc[pd.Timestamp(effective_date)] = rate
    series = series.ffill()

    # sanity: mean over 2017-07-01..2026-08-31 comes out to ~2.58% against this
    # schedule (checked at authoring time, 2026-08-22). Spec §5 Table 8 states a
    # mean policy rate of 2.53% over the same window.
    # CONTRACT-NOTE: 2.58% vs the spec's 2.53% is a 5bp (about 2% relative) gap.
    # Plausible explanation: this schedule uses the target-range MIDPOINT at
    # every step (per this module's contract) rather than the realised
    # effective rate, which historically sits a few bp inside the range rather
    # than exactly at its midpoint. Not investigated further — flagging per the
    # project's "no silent skip" rule rather than silently accepting either the
    # gap or forcing the numbers to match.

    return series


def fred_policy_rates(start: str, end: str, api_key: str | None = None) -> pd.Series:
    """Fetch the effective Fed Funds rate (FRED series DFF) as a decimal series.

    `api_key` is accepted for interface symmetry with other FRED-backed
    fetchers but is unused: the plain `fredgraph.csv` endpoint used here is
    public and needs no key. Never raises — any failure (network, parsing,
    missing dependency) is logged as a warning and `embedded_policy_rates()` is
    returned instead, so a live run never blocks on FRED being unreachable.
    """
    del api_key  # unused: public fredgraph.csv endpoint needs no key
    url = f"{_FRED_URL}&cosd={start}&coed={end}"
    try:
        if httpx is not None:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url)
                response.raise_for_status()
                text = response.text
        else:  # pragma: no cover - only hit if httpx is somehow unavailable
            with urllib.request.urlopen(url, timeout=10.0) as response:
                text = response.read().decode("utf-8")

        frame = pd.read_csv(io.StringIO(text))
        date_col, rate_col = frame.columns[0], frame.columns[1]
        frame[date_col] = pd.to_datetime(frame[date_col])
        rate = pd.to_numeric(frame[rate_col], errors="coerce")
        series = pd.Series(rate.to_numpy(), index=frame[date_col], name="policy_rate")
        series = series.dropna() / 100.0
        if series.empty:
            raise ValueError("FRED DFF response contained no usable observations")
        return series
    except Exception as exc:  # must never raise: any failure falls back to the embedded schedule
        logger.warning(
            "programme_fred_policy_rates_fallback",
            error=str(exc),
            start=start,
            end=end,
        )
        return embedded_policy_rates()


def policy_rate_path(
    index: pd.DatetimeIndex, source: str = "embedded", api_key: str | None = None
) -> pd.Series:
    """Reindex the chosen policy-rate source onto `index`.

    Forward-fills gaps, then back-fills any leading NaN (dates in `index`
    before the source series starts) with the first available value. If every
    date in `index` precedes the source's first observation (2015-01-01 for
    the embedded schedule), there is nothing to back-fill from and the result
    is all-NaN for those dates — this reflects the embedded schedule's
    documented 2015-01-01 start, not a bug.
    """
    if source == "embedded":
        raw = embedded_policy_rates()
    elif source == "fred":
        start = str(pd.Timestamp(index.min()).date())
        end = str(pd.Timestamp(index.max()).date())
        raw = fred_policy_rates(start, end, api_key=api_key)
    else:
        raise ConfigError(
            f"Unknown policy rate source: {source!r}", detail="expected 'embedded' or 'fred'"
        )

    return raw.reindex(index).ffill().bfill()
