"""Unit tests for domain entities.

Pure Python — no I/O, no fixtures, no mocks.
Tests that domain invariants are enforced at construction time.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from aurelius.domain.entities.market import (
    OHLCV,
    AssetClass,
    DataFrequency,
    Exchange,
    Quote,
    Symbol,
    TimeRange,
)


class TestSymbol:
    def test_ticker_normalized_to_uppercase(self) -> None:
        s = Symbol(ticker="aapl")
        assert s.ticker == "AAPL"

    def test_ticker_stripped(self) -> None:
        s = Symbol(ticker="  MSFT  ")
        assert s.ticker == "MSFT"

    def test_equality_same_ticker_exchange(self) -> None:
        a = Symbol(ticker="AAPL", exchange=Exchange.NASDAQ)
        b = Symbol(ticker="AAPL", exchange=Exchange.NASDAQ)
        assert a == b

    def test_inequality_different_exchange(self) -> None:
        a = Symbol(ticker="SPY", exchange=Exchange.NYSE)
        b = Symbol(ticker="SPY", exchange=Exchange.NASDAQ)
        assert a != b

    def test_hashable_for_dict_key(self) -> None:
        s = Symbol(ticker="AAPL", exchange=Exchange.NASDAQ)
        d = {s: "apple"}
        assert d[s] == "apple"

    def test_str_representation(self) -> None:
        s = Symbol(ticker="AAPL", exchange=Exchange.NASDAQ)
        assert str(s) == "AAPL:NASDAQ"

    def test_empty_ticker_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 1 character"):
            Symbol(ticker="")

    def test_default_asset_class_is_equity(self) -> None:
        s = Symbol(ticker="AAPL")
        assert s.asset_class == AssetClass.EQUITY


class TestOHLCV:
    def _symbol(self) -> Symbol:
        return Symbol(ticker="AAPL", exchange=Exchange.NASDAQ)

    def _valid_bar(self) -> OHLCV:
        return OHLCV(
            symbol=self._symbol(),
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=UTC),
            frequency=DataFrequency.DAY,
            open=Decimal("150.00"),
            high=Decimal("155.00"),
            low=Decimal("148.00"),
            close=Decimal("153.00"),
            volume=Decimal("1000000"),
        )

    def test_valid_bar_constructs(self) -> None:
        bar = self._valid_bar()
        assert bar.close == Decimal("153.00")

    def test_high_less_than_low_raises(self) -> None:
        with pytest.raises(Exception, match="high"):
            OHLCV(
                symbol=self._symbol(),
                timestamp=datetime(2024, 1, 15, tzinfo=UTC),
                frequency=DataFrequency.DAY,
                open=Decimal("150"),
                high=Decimal("140"),  # high < low
                low=Decimal("148"),
                close=Decimal("145"),
                volume=Decimal("1000000"),
            )

    def test_high_less_than_open_raises(self) -> None:
        with pytest.raises(ValueError, match="must be >="):
            OHLCV(
                symbol=self._symbol(),
                timestamp=datetime(2024, 1, 15, tzinfo=UTC),
                frequency=DataFrequency.DAY,
                open=Decimal("160"),  # open > high
                high=Decimal("155"),
                low=Decimal("148"),
                close=Decimal("153"),
                volume=Decimal("1000000"),
            )

    def test_negative_price_raises(self) -> None:
        with pytest.raises(ValueError, match="greater than 0"):
            OHLCV(
                symbol=self._symbol(),
                timestamp=datetime(2024, 1, 15, tzinfo=UTC),
                frequency=DataFrequency.DAY,
                open=Decimal("-1"),
                high=Decimal("155"),
                low=Decimal("148"),
                close=Decimal("153"),
                volume=Decimal("1000000"),
            )

    def test_is_green_close_above_open(self) -> None:
        bar = self._valid_bar()
        assert bar.is_green is True

    def test_is_red_close_below_open(self) -> None:
        bar = OHLCV(
            symbol=self._symbol(),
            timestamp=datetime(2024, 1, 15, tzinfo=UTC),
            frequency=DataFrequency.DAY,
            open=Decimal("155"),
            high=Decimal("156"),
            low=Decimal("148"),
            close=Decimal("149"),
            volume=Decimal("1000000"),
        )
        assert bar.is_green is False

    def test_body_size(self) -> None:
        bar = self._valid_bar()
        assert bar.body_size == Decimal("3.00")  # |153 - 150|

    def test_range_size(self) -> None:
        bar = self._valid_bar()
        assert bar.range_size == Decimal("7.00")  # 155 - 148


class TestQuote:
    def _symbol(self) -> Symbol:
        return Symbol(ticker="MSFT")

    def test_spread_computed(self) -> None:
        q = Quote(
            symbol=self._symbol(),
            timestamp=datetime(2024, 1, 15, tzinfo=UTC),
            bid_price=Decimal("299.98"),
            ask_price=Decimal("300.02"),
            bid_size=Decimal("100"),
            ask_size=Decimal("200"),
        )
        assert q.spread == Decimal("0.04")

    def test_mid_price_computed(self) -> None:
        q = Quote(
            symbol=self._symbol(),
            timestamp=datetime(2024, 1, 15, tzinfo=UTC),
            bid_price=Decimal("100.00"),
            ask_price=Decimal("100.02"),
            bid_size=Decimal("100"),
            ask_size=Decimal("100"),
        )
        assert q.mid_price == Decimal("100.01")

    def test_inverted_spread_raises(self) -> None:
        with pytest.raises(Exception, match="ask"):
            Quote(
                symbol=self._symbol(),
                timestamp=datetime(2024, 1, 15, tzinfo=UTC),
                bid_price=Decimal("100.10"),
                ask_price=Decimal("100.00"),  # ask < bid
                bid_size=Decimal("100"),
                ask_size=Decimal("100"),
            )


class TestTimeRange:
    def test_valid_range(self) -> None:
        tr = TimeRange(
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 12, 31, tzinfo=UTC),
        )
        assert tr.start < tr.end

    def test_end_before_start_raises(self) -> None:
        with pytest.raises(Exception, match="end"):
            TimeRange(
                start=datetime(2024, 12, 31, tzinfo=UTC),
                end=datetime(2024, 1, 1, tzinfo=UTC),
            )

    def test_equal_start_end_raises(self) -> None:
        dt = datetime(2024, 1, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="must be after"):
            TimeRange(start=dt, end=dt)
