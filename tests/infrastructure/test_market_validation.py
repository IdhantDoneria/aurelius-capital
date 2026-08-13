"""Tests for OHLCVIngest, OHLCVBatchValidator, CorporateActionIngest.

market.py validation at 73% — quality score, vwap range check, staleness,
chronological order, corporate action validators all untested.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from mentisrex.infrastructure.database.validation.market import (
    CorporateActionIngest,
    OHLCVBatchValidator,
    OHLCVIngest,
    ValidationResult,
)

_SYM = uuid4()
_SRC = uuid4()
_TS = datetime(2024, 1, 15, tzinfo=UTC)


def _bar(**kw) -> dict:
    defaults = {
        "symbol_id": _SYM,
        "source_id": _SRC,
        "timestamp": _TS,
        "frequency": "1d",
        "open": Decimal("185.00"),
        "high": Decimal("186.50"),
        "low": Decimal("184.00"),
        "close": Decimal("185.80"),
        "volume": Decimal("50000000"),
    }
    defaults.update(kw)
    return defaults


# ── OHLCVIngest field-level ────────────────────────────────────────────────────


@pytest.mark.unit
def test_ohlcv_valid_bar():
    bar = OHLCVIngest(**_bar())
    assert bar.close == Decimal("185.80")


@pytest.mark.unit
def test_ohlcv_high_lt_low_rejected():
    with pytest.raises(Exception, match=r"high.*low"):
        OHLCVIngest(**_bar(high=Decimal("183"), low=Decimal("187")))


@pytest.mark.unit
def test_ohlcv_high_lt_open_rejected():
    with pytest.raises(Exception, match=r"high.*open"):
        OHLCVIngest(**_bar(open=Decimal("190"), high=Decimal("186")))


@pytest.mark.unit
def test_ohlcv_high_lt_close_rejected():
    with pytest.raises(Exception, match=r"high.*close"):
        OHLCVIngest(**_bar(close=Decimal("190"), high=Decimal("186")))


@pytest.mark.unit
def test_ohlcv_low_gt_open_rejected():
    with pytest.raises(Exception, match=r"low.*open"):
        OHLCVIngest(**_bar(open=Decimal("183"), low=Decimal("184")))


@pytest.mark.unit
def test_ohlcv_vwap_outside_range_rejected():
    with pytest.raises(Exception, match="vwap"):
        OHLCVIngest(**_bar(vwap=Decimal("200")))  # above high


@pytest.mark.unit
def test_ohlcv_vwap_within_range_accepted():
    bar = OHLCVIngest(**_bar(vwap=Decimal("185.20")))
    assert bar.vwap == Decimal("185.20")


@pytest.mark.unit
def test_ohlcv_vwap_none_accepted():
    bar = OHLCVIngest(**_bar())
    assert bar.vwap is None


@pytest.mark.unit
def test_ohlcv_invalid_frequency_rejected():
    with pytest.raises(Exception, match="frequency"):
        OHLCVIngest(**_bar(frequency="3h"))  # not in valid set


@pytest.mark.unit
def test_ohlcv_naive_timestamp_rejected():
    with pytest.raises(Exception, match="timezone-aware"):
        OHLCVIngest(**_bar(timestamp=datetime(2024, 1, 15)))  # naive


@pytest.mark.unit
def test_ohlcv_zero_price_rejected():
    with pytest.raises(ValueError, match=".*"):
        OHLCVIngest(**_bar(open=Decimal("0")))


@pytest.mark.unit
def test_ohlcv_negative_volume_rejected():
    with pytest.raises(ValueError, match=".*"):
        OHLCVIngest(**_bar(volume=Decimal("-1")))


@pytest.mark.unit
def test_ohlcv_zero_volume_accepted():
    # Zero volume is allowed (halted stock), but penalizes quality score
    bar = OHLCVIngest(**_bar(volume=Decimal("0")))
    assert bar.volume == Decimal("0")


# ── compute_quality_score ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_quality_perfect_score():
    bar = OHLCVIngest(**_bar(vwap=Decimal("185.20"), trade_count=120000))
    score = bar.compute_quality_score(prev_close=Decimal("185.00"))
    assert score == 100


@pytest.mark.unit
def test_quality_missing_vwap_deducts_10():
    bar = OHLCVIngest(**_bar(trade_count=100000))
    score = bar.compute_quality_score()
    assert score == 90  # -10 for missing vwap


@pytest.mark.unit
def test_quality_missing_trade_count_deducts_5():
    bar = OHLCVIngest(**_bar(vwap=Decimal("185.20")))
    score = bar.compute_quality_score()
    assert score == 95  # -5 for missing trade_count


@pytest.mark.unit
def test_quality_zero_volume_deducts_30():
    # vwap=None (-10), trade_count=None (-5), volume=0 (-30) = 55
    bar = OHLCVIngest(**_bar(volume=Decimal("0"), vwap=None))
    score = bar.compute_quality_score()
    assert score == 55  # 100 - 10 - 5 - 30


@pytest.mark.unit
def test_quality_large_move_deducts_20():
    # Bar where close is ~24% above prev_close; high must accommodate close
    bar = OHLCVIngest(
        **_bar(
            open=Decimal("184.00"),
            high=Decimal("231.00"),
            low=Decimal("183.00"),
            close=Decimal("230.00"),
        )
    )
    score = bar.compute_quality_score(prev_close=Decimal("185.00"))
    # vwap=None (-10), trade_count=None (-5), >20% move (-20) = 65
    assert score <= 75


@pytest.mark.unit
def test_quality_huge_move_deducts_40():
    # >50% move: -20 for >20% AND -20 for >50%
    bar = OHLCVIngest(**_bar(close=Decimal("300.00"), high=Decimal("310.00")))
    score = bar.compute_quality_score(prev_close=Decimal("185.00"))
    assert score < 60


@pytest.mark.unit
def test_quality_score_never_negative():
    bar = OHLCVIngest(**_bar(volume=Decimal("0"), close=Decimal("300.00"), high=Decimal("310.00")))
    score = bar.compute_quality_score(prev_close=Decimal("185.00"))
    assert score >= 0


@pytest.mark.unit
def test_quality_zero_prev_close_safe():
    # Must not raise ZeroDivisionError
    bar = OHLCVIngest(**_bar())
    score = bar.compute_quality_score(prev_close=Decimal("0"))
    assert isinstance(score, int)


# ── OHLCVBatchValidator ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_batch_validator_rejects_invalid_bars():
    validator = OHLCVBatchValidator()
    bad = _bar(high=Decimal("180"), low=Decimal("190"))  # high < low
    valid, rejected = validator.validate_batch([bad])
    assert len(valid) == 0
    assert len(rejected) == 1
    assert "validation_errors" in rejected[0]


@pytest.mark.unit
def test_batch_validator_passes_valid_bars():
    validator = OHLCVBatchValidator()
    valid, rejected = validator.validate_batch([_bar()])
    assert len(valid) == 1
    assert len(rejected) == 0


@pytest.mark.unit
def test_batch_validator_empty_input():
    validator = OHLCVBatchValidator()
    valid, rejected = validator.validate_batch([])
    assert valid == []
    assert rejected == []


@pytest.mark.unit
def test_batch_validator_mixed_batch():
    validator = OHLCVBatchValidator()
    good = _bar()
    bad = _bar(high=Decimal("180"), low=Decimal("190"))
    valid, rejected = validator.validate_batch([good, bad])
    assert len(valid) == 1
    assert len(rejected) == 1


@pytest.mark.unit
def test_chronological_order_out_of_order_flagged():
    validator = OHLCVBatchValidator()
    bar1 = OHLCVIngest(**_bar(timestamp=datetime(2024, 1, 15, tzinfo=UTC)))
    bar2 = OHLCVIngest(**_bar(timestamp=datetime(2024, 1, 10, tzinfo=UTC)))  # earlier!
    issues = validator.validate_chronological_order([bar1, bar2])
    assert len(issues) == 1
    assert issues[0].field == "timestamp"


@pytest.mark.unit
def test_chronological_order_in_order_no_issues():
    validator = OHLCVBatchValidator()
    bar1 = OHLCVIngest(**_bar(timestamp=datetime(2024, 1, 10, tzinfo=UTC)))
    bar2 = OHLCVIngest(**_bar(timestamp=datetime(2024, 1, 15, tzinfo=UTC)))
    assert validator.validate_chronological_order([bar1, bar2]) == []


@pytest.mark.unit
def test_chronological_single_bar_no_issues():
    validator = OHLCVBatchValidator()
    bar = OHLCVIngest(**_bar())
    assert validator.validate_chronological_order([bar]) == []


# ── CorporateActionIngest ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_split_requires_ratio():
    with pytest.raises(Exception, match="ratio is required"):
        CorporateActionIngest(
            symbol_id=_SYM,
            action_type="split",
            ex_date=_TS,
            data_source="test",
        )


@pytest.mark.unit
def test_split_with_ratio_valid():
    ca = CorporateActionIngest(
        symbol_id=_SYM,
        action_type="split",
        ex_date=_TS,
        ratio=Decimal("2"),
        data_source="test",
    )
    assert ca.ratio == Decimal("2")


@pytest.mark.unit
def test_dividend_cash_requires_cash_amount():
    with pytest.raises(Exception, match="cash_amount is required"):
        CorporateActionIngest(
            symbol_id=_SYM,
            action_type="dividend_cash",
            ex_date=_TS,
            data_source="test",
        )


@pytest.mark.unit
def test_dividend_cash_with_amount_valid():
    ca = CorporateActionIngest(
        symbol_id=_SYM,
        action_type="dividend_cash",
        ex_date=_TS,
        cash_amount=Decimal("1.25"),
        data_source="test",
    )
    assert ca.cash_amount == Decimal("1.25")


@pytest.mark.unit
def test_invalid_action_type_rejected():
    with pytest.raises(Exception, match="action_type"):
        CorporateActionIngest(
            symbol_id=_SYM,
            action_type="buyback",  # not in valid set
            ex_date=_TS,
            data_source="test",
        )


# ── ValidationResult ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_validation_result_add_error_marks_invalid():
    r = ValidationResult(is_valid=True)
    r.add_error("close", "must be positive")
    assert not r.is_valid
    assert len(r.errors) == 1
    assert r.errors[0].field == "close"


@pytest.mark.unit
def test_validation_result_add_warning_stays_valid():
    r = ValidationResult(is_valid=True)
    r.add_warning("timestamp", "bar is old")
    assert r.is_valid
    assert len(r.warnings) == 1
    assert len(r.errors) == 0
