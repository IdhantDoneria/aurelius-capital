"""Tests for CSV loader and normalizer — no I/O mocking needed."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from mentisrex.market_data.adapters.base import RawBar
from mentisrex.market_data.adapters.csv_loader import CSVLoader, _parse_timestamp
from mentisrex.market_data.pipeline.normalizer import (
    compute_spike,
    detect_gaps,
    normalize_bar,
    to_utc,
)

# ── timestamp parsing ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_parse_timestamp_iso():
    dt = _parse_timestamp("2024-01-15")
    assert dt.tzinfo is not None
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 15


@pytest.mark.unit
def test_parse_timestamp_iso_with_tz():
    dt = _parse_timestamp("2024-01-15T10:30:00Z")
    assert dt.tzinfo is not None
    assert dt.hour == 10


@pytest.mark.unit
def test_parse_timestamp_us_format():
    dt = _parse_timestamp("01/15/2024")
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 15


@pytest.mark.unit
def test_parse_timestamp_invalid_raises():
    with pytest.raises(ValueError, match="Cannot parse"):
        _parse_timestamp("not-a-date")


# ── normalizer ───────────────────────────────────────────────────────────────


def _bar(**kwargs) -> RawBar:
    defaults = {
        "symbol": "aapl",
        "timestamp": datetime(2024, 1, 15, 14, 30),
        "open": Decimal("185.00"),
        "high": Decimal("186.50"),
        "low": Decimal("184.00"),
        "close": Decimal("185.80"),
        "volume": Decimal("50000000"),
        "frequency": "1d",
        "source": "test",
    }
    return RawBar(**{**defaults, **kwargs})


@pytest.mark.unit
def test_normalize_bar_uppercases_symbol():
    bar = _bar(symbol="aapl")
    assert normalize_bar(bar).symbol == "AAPL"


@pytest.mark.unit
def test_normalize_bar_adds_utc_to_naive():
    bar = _bar(timestamp=datetime(2024, 1, 15))
    normalized = normalize_bar(bar)
    assert normalized.timestamp.tzinfo is not None


@pytest.mark.unit
def test_normalize_bar_converts_negative_volume():
    bar = _bar(volume=Decimal("-1"))
    assert normalize_bar(bar).volume == Decimal("0")


@pytest.mark.unit
def test_to_utc_preserves_aware():
    aware = datetime(2024, 1, 15, tzinfo=UTC)
    assert to_utc(aware) == aware


@pytest.mark.unit
def test_to_utc_adds_utc_to_naive():
    naive = datetime(2024, 1, 15)
    result = to_utc(naive)
    assert result.tzinfo is not None


# ── gap detection ─────────────────────────────────────────────────────────────


def _ts(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


@pytest.mark.unit
def test_detect_gaps_normal_weekend_not_flagged():
    bars = [
        _bar(timestamp=_ts(2024, 1, 12)),  # Friday
        _bar(timestamp=_ts(2024, 1, 15)),  # Monday (3-day gap, normal)
    ]
    assert detect_gaps(bars) == []


@pytest.mark.unit
def test_detect_gaps_flags_large_gap():
    bars = [
        _bar(timestamp=_ts(2024, 1, 10)),
        _bar(timestamp=_ts(2024, 1, 20)),  # 10-day gap
    ]
    gaps = detect_gaps(bars)
    assert len(gaps) == 1
    assert gaps[0] == _ts(2024, 1, 10)


@pytest.mark.unit
def test_detect_gaps_empty_list():
    assert detect_gaps([]) == []


@pytest.mark.unit
def test_detect_gaps_single_bar():
    assert detect_gaps([_bar()]) == []


@pytest.mark.unit
def test_detect_gaps_custom_threshold():
    bars = [
        _bar(timestamp=_ts(2024, 1, 10)),
        _bar(timestamp=_ts(2024, 1, 13)),  # 3-day gap
    ]
    assert detect_gaps(bars, max_gap_days=4) == []
    assert len(detect_gaps(bars, max_gap_days=2)) == 1


# ── spike detection ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_compute_spike_detects_large_move():
    bar = _bar(close=Decimal("240.00"))  # 30% above 185
    assert compute_spike(bar, prev_close=Decimal("185.00"), threshold=Decimal("0.20"))


@pytest.mark.unit
def test_compute_spike_ignores_small_move():
    bar = _bar(close=Decimal("186.00"))  # ~0.5% move
    assert not compute_spike(bar, prev_close=Decimal("185.00"))


@pytest.mark.unit
def test_compute_spike_zero_prev_close_safe():
    bar = _bar(close=Decimal("185.00"))
    assert not compute_spike(bar, prev_close=Decimal("0"))


# ── CSV loader ────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    content = (
        "date,open,high,low,close,volume,vwap\n"
        "2024-01-02,185.00,186.50,184.00,185.80,50000000,185.40\n"
        "2024-01-03,185.80,187.20,185.00,186.90,45000000,186.10\n"
        "2024-01-04,186.90,187.00,183.00,184.50,55000000,185.00\n"
    )
    p = tmp_path / "aapl.csv"
    p.write_text(content)
    return p


@pytest.mark.unit
def test_csv_loader_parses_bars(sample_csv: Path):
    bars = CSVLoader().load_file(sample_csv, default_symbol="AAPL")
    assert len(bars) == 3
    assert all(b.symbol == "AAPL" for b in bars)
    assert bars[0].open == Decimal("185.00")
    assert bars[0].vwap == Decimal("185.40")


@pytest.mark.unit
def test_csv_loader_sets_frequency(sample_csv: Path):
    bars = CSVLoader().load_file(sample_csv, default_symbol="AAPL", frequency="1d")
    assert all(b.frequency == "1d" for b in bars)


@pytest.mark.unit
def test_csv_loader_timestamps_are_utc(sample_csv: Path):
    bars = CSVLoader().load_file(sample_csv, default_symbol="AAPL")
    assert all(b.timestamp.tzinfo is not None for b in bars)


@pytest.mark.unit
def test_csv_loader_missing_file_raises():
    with pytest.raises(Exception, match="not found"):
        CSVLoader().load_file(Path("/nonexistent/file.csv"))


@pytest.mark.unit
def test_csv_loader_with_symbol_column(tmp_path: Path):
    content = (
        "symbol,date,open,high,low,close,volume\n"
        "AAPL,2024-01-02,185.00,186.50,184.00,185.80,50000000\n"
        "MSFT,2024-01-02,375.00,377.00,373.00,376.00,25000000\n"
    )
    p = tmp_path / "multi.csv"
    p.write_text(content)
    bars = CSVLoader().load_file(p)
    symbols = {b.symbol for b in bars}
    assert symbols == {"AAPL", "MSFT"}


@pytest.mark.unit
def test_csv_loader_skips_bad_rows(tmp_path: Path):
    content = (
        "date,open,high,low,close,volume\n"
        "2024-01-02,185.00,186.50,184.00,185.80,50000000\n"
        "not-a-date,185.00,186.50,184.00,185.80,50000000\n"  # bad date
        "2024-01-04,bad,186.50,184.00,185.80,50000000\n"  # bad price
    )
    p = tmp_path / "bad.csv"
    p.write_text(content)
    bars = CSVLoader().load_file(p, default_symbol="AAPL")
    assert len(bars) == 1  # only first row is valid
