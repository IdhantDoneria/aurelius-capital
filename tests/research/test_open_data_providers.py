"""M21 open data provider tests (AIDP M21).

All tests: offline, deterministic, no network. Provider adapters are exercised via their
convert() methods with fixture dicts. PIT safety, fingerprint stability, schema correctness,
and the full Provider → M20 → M19 → M18 snapshot pipeline are validated.

pytest tests/research/test_open_data_providers.py
"""

from __future__ import annotations

import time
from datetime import date

import pytest

from mentisrex.research.market_data.analytics.fundamentals import (
    FundamentalObservation,
    FundamentalRatioEngine,
)
from mentisrex.research.market_data.export.lean import LeanExporter
from mentisrex.research.market_data.normalization import Normalizer
from mentisrex.research.market_data.pit import MarketDataSnapshotBuilder
from mentisrex.research.market_data.providers import ALL_PROVIDERS, ProviderMetadata, default_m21_registry
from mentisrex.research.market_data.providers.financetoolkit import FinanceToolkitSourceAdapter
from mentisrex.research.market_data.providers.fincept import FinceptSourceAdapter
from mentisrex.research.market_data.providers.fred import FREDSourceAdapter
from mentisrex.research.market_data.providers.india import IndiaSourceAdapter
from mentisrex.research.market_data.providers.openbb import OpenBBSourceAdapter
from mentisrex.research.market_data.providers.qlib import QlibExporter, QlibSourceAdapter
from mentisrex.research.market_data.providers.sec import SECSourceAdapter
from mentisrex.research.market_data.providers.yahoo import YahooFinanceSourceAdapter
from mentisrex.research.market_data_ops.adapters import MessageLogAdapter
from mentisrex.research.market_data_ops.messages import MessageType, SourceMessage

AS_OF = date(2024, 6, 30)
FUTURE = date(2025, 1, 1)


# ── Provider metadata & registry ────────────────────────────────────────────

class TestProviderRegistry:
    def test_all_providers_have_metadata(self):
        assert len(ALL_PROVIDERS) == 8  # openbb, fincept, yahoo, sec, fred, india, qlib, ftk

    def test_provider_fingerprint_stable(self):
        meta = ProviderMetadata(
            name="test", version="1.0.0", license="MIT",
            coverage="global", datasets=("ohlcv",), limitations=("none",),
        )
        assert len(meta.fingerprint) == 16  # blake2b 8-byte = 16 hex chars
        # same inputs → same fingerprint
        meta2 = ProviderMetadata(
            name="test", version="1.0.0", license="MIT",
            coverage="global", datasets=("ohlcv",), limitations=("none",),
        )
        assert meta.fingerprint == meta2.fingerprint

    def test_m21_registry_registers_all(self):
        r = default_m21_registry()
        names = {info.name for info in r.all()}
        for meta in ALL_PROVIDERS:
            assert f"m21.{meta.name}" in names

    def test_provider_fingerprints_unique(self):
        fps = [m.fingerprint for m in ALL_PROVIDERS]
        assert len(fps) == len(set(fps)), "provider fingerprints must be unique"


# ── OpenBB adapter ────────────────────────────────────────────────────────────

class TestOpenBBAdapter:
    def _adapter(self):
        return OpenBBSourceAdapter()

    def _equity_record(self, symbol="AAPL", d=None, close=150.0):
        return {"symbol": symbol, "date": (d or AS_OF).isoformat(),
                "open": 148.0, "high": 152.0, "low": 147.0,
                "close": close, "volume": 50_000_000, "currency": "USD"}

    def test_equity_conversion(self):
        adapter = self._adapter()
        msgs = adapter.convert([self._equity_record()], AS_OF)
        assert len(msgs) == 1
        m = msgs[0]
        assert m.source == "openbb"
        assert m.payload["id"] == "AAPL"
        assert m.payload["field"] == "close"
        assert m.payload["value"] == 150.0
        assert m.payload["currency"] == "USD"
        assert m.observation_date == AS_OF
        assert m.effective_date == AS_OF

    def test_adj_close_preferred_over_close(self):
        r = self._equity_record()
        r["adj_close"] = 149.0
        msgs = self._adapter().convert([r], AS_OF)
        assert msgs[0].payload["type"] == "adjusted_close"
        assert msgs[0].payload["value"] == 149.0

    def test_macro_record(self):
        rec = {"date": AS_OF.isoformat(), "series_id": "GDP", "value": 27357.0, "unit": "USD"}
        msgs = self._adapter().convert([rec], AS_OF)
        assert len(msgs) == 1
        assert msgs[0].payload["id"] == "GDP"
        assert msgs[0].payload["value"] == 27357.0

    def test_fx_record(self):
        rec = {"date": AS_OF.isoformat(), "base": "EUR", "quote": "USD", "rate": 1.085}
        msgs = self._adapter().convert([rec], AS_OF)
        assert len(msgs) == 1
        assert msgs[0].payload["field"] == "fx_rate"
        assert msgs[0].payload["value"] == 1.085

    def test_future_records_rejected(self):
        r = self._equity_record(d=FUTURE)
        msgs = self._adapter().convert([r], AS_OF)
        assert len(msgs) == 0  # future record must be dropped

    def test_missing_date_skipped(self):
        r = {"symbol": "AAPL", "close": 150.0}  # no date
        msgs = self._adapter().convert([r], AS_OF)
        assert len(msgs) == 0

    def test_fingerprint_stable(self):
        r = self._equity_record()
        a1 = OpenBBSourceAdapter()
        a2 = OpenBBSourceAdapter()
        m1 = a1.convert([r], AS_OF)[0]
        m2 = a2.convert([r], AS_OF)[0]
        assert m1.raw_fingerprint() == m2.raw_fingerprint()

    def test_sequences_monotone(self):
        records = [self._equity_record(symbol=f"S{i}") for i in range(10)]
        msgs = self._adapter().convert(records, AS_OF)
        seqs = [m.sequence for m in msgs]
        assert seqs == list(range(1, 11))

    def test_multiple_fields_in_payload(self):
        msgs = self._adapter().convert([self._equity_record()], AS_OF)
        payload = msgs[0].payload
        assert "open" in payload and "high" in payload and "low" in payload and "volume" in payload


# ── Fincept adapter ───────────────────────────────────────────────────────────

class TestFinceptAdapter:
    def test_basic_conversion(self):
        rec = {"id": "RELIANCE", "date": AS_OF.isoformat(), "field": "close",
               "value": 2500.0, "source": "fincept", "currency": "INR"}
        msgs = FinceptSourceAdapter().convert([rec], AS_OF)
        assert len(msgs) == 1
        assert msgs[0].payload["id"] == "RELIANCE"
        assert msgs[0].payload["value"] == 2500.0

    def test_missing_id_skipped(self):
        rec = {"date": AS_OF.isoformat(), "field": "close", "value": 100.0}
        assert FinceptSourceAdapter().convert([rec], AS_OF) == []

    def test_malformed_value_skipped(self):
        rec = {"id": "X", "date": AS_OF.isoformat(), "field": "close", "value": "not_a_number"}
        assert FinceptSourceAdapter().convert([rec], AS_OF) == []

    def test_future_rejected(self):
        rec = {"id": "X", "date": FUTURE.isoformat(), "field": "close", "value": 100.0}
        assert FinceptSourceAdapter().convert([rec], AS_OF) == []

    def test_fetch_raises(self):
        with pytest.raises(NotImplementedError):
            FinceptSourceAdapter().fetch(AS_OF)


# ── Yahoo Finance adapter ─────────────────────────────────────────────────────

class TestYahooAdapter:
    def _record(self, symbol="MSFT", d=None, close=300.0, adj_close=None, div=0.0, split=0.0):
        r = {
            "symbol": symbol, "date": (d or AS_OF).isoformat(),
            "open": 298.0, "high": 302.0, "low": 297.0, "close": close,
            "volume": 20_000_000, "dividends": div, "stock_splits": split,
        }
        if adj_close is not None:
            r["adj_close"] = adj_close
        return r

    def test_close_emitted(self):
        msgs = YahooFinanceSourceAdapter().convert([self._record()], AS_OF)
        close_msgs = [m for m in msgs if m.payload.get("type") == "close"]
        assert len(close_msgs) == 1
        assert close_msgs[0].payload["value"] == 300.0

    def test_adj_close_separate_message(self):
        msgs = YahooFinanceSourceAdapter().convert([self._record(adj_close=298.5)], AS_OF)
        types = {m.payload.get("type") for m in msgs}
        assert "close" in types and "adjusted_close" in types

    def test_adj_close_equals_close_no_duplicate(self):
        msgs = YahooFinanceSourceAdapter().convert([self._record(close=300.0, adj_close=300.0)], AS_OF)
        types = [m.payload.get("type") for m in msgs]
        assert types.count("close") == 1
        assert "adjusted_close" not in types

    def test_dividend_emitted_as_reference(self):
        msgs = YahooFinanceSourceAdapter().convert([self._record(div=0.25)], AS_OF)
        div_msgs = [m for m in msgs if m.payload.get("type") == "dividend"]
        assert len(div_msgs) == 1
        assert div_msgs[0].msg_type == MessageType.REFERENCE
        assert div_msgs[0].payload["value"] == 0.25

    def test_split_emitted_as_reference(self):
        msgs = YahooFinanceSourceAdapter().convert([self._record(split=4.0)], AS_OF)
        split_msgs = [m for m in msgs if m.payload.get("type") == "split"]
        assert len(split_msgs) == 1
        assert split_msgs[0].payload["value"] == 4.0

    def test_zero_split_not_emitted(self):
        msgs = YahooFinanceSourceAdapter().convert([self._record(split=0.0)], AS_OF)
        assert not any(m.payload.get("type") == "split" for m in msgs)

    def test_future_rejected(self):
        msgs = YahooFinanceSourceAdapter().convert([self._record(d=FUTURE)], AS_OF)
        assert len(msgs) == 0

    def test_id_map_resolution(self):
        from mentisrex.research.market_data.identifiers import IdType, IdentifierMap
        id_map = IdentifierMap()
        id_map.add(IdType.TICKER, "MSFT", "sec_msft_001")
        adapter = YahooFinanceSourceAdapter(id_map=id_map)
        msgs = adapter.convert([self._record()], AS_OF)
        assert any(m.payload["id"] == "sec_msft_001" for m in msgs)

    def test_fingerprint_stable(self):
        r = self._record()
        m1 = YahooFinanceSourceAdapter().convert([r], AS_OF)[0]
        m2 = YahooFinanceSourceAdapter().convert([r], AS_OF)[0]
        assert m1.raw_fingerprint() == m2.raw_fingerprint()


# ── SEC/EDGAR adapter ─────────────────────────────────────────────────────────

def _apple_company_facts(filed="2022-10-28", end="2022-09-24", revenue=394328000000):
    return {
        "cik": "0000320193",
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"end": end, "val": revenue,
                             "accn": "0000320193-22-000108",
                             "fy": 2022, "fp": "FY", "form": "10-K",
                             "filed": filed}
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {"end": end, "val": 99803000000,
                             "accn": "0000320193-22-000108",
                             "fy": 2022, "fp": "FY", "form": "10-K",
                             "filed": filed}
                        ]
                    }
                },
            }
        },
    }


class TestSECAdapter:
    def test_basic_conversion(self):
        facts = _apple_company_facts()
        msgs = SECSourceAdapter().convert(facts, AS_OF, security_id="aapl_sec")
        assert len(msgs) > 0
        revenue_msgs = [m for m in msgs if m.payload.get("field") == "revenue"]
        assert len(revenue_msgs) == 1

    def test_pit_filed_date_is_observation_date(self):
        facts = _apple_company_facts(filed="2022-10-28", end="2022-09-24")
        msgs = SECSourceAdapter().convert(facts, AS_OF, security_id="aapl")
        revenue_msgs = [m for m in msgs if m.payload.get("field") == "revenue"]
        assert revenue_msgs[0].observation_date == date(2022, 10, 28)

    def test_pit_period_end_is_effective_date(self):
        facts = _apple_company_facts(filed="2022-10-28", end="2022-09-24")
        msgs = SECSourceAdapter().convert(facts, AS_OF, security_id="aapl")
        revenue_msgs = [m for m in msgs if m.payload.get("field") == "revenue"]
        assert revenue_msgs[0].effective_date == date(2022, 9, 24)

    def test_future_filing_rejected(self):
        facts = _apple_company_facts(filed=FUTURE.isoformat())
        msgs = SECSourceAdapter().convert(facts, AS_OF, security_id="aapl")
        assert len(msgs) == 0

    def test_revision_numbering(self):
        facts = {
            "cik": "1", "entityName": "TestCo",
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"end": "2022-12-31", "val": 1000, "accn": "0001",
                                 "fy": 2022, "fp": "FY", "form": "10-K", "filed": "2023-03-15"},
                                {"end": "2022-12-31", "val": 1050, "accn": "0002",
                                 "fy": 2022, "fp": "FY", "form": "10-K/A", "filed": "2023-05-01"},
                            ]
                        }
                    }
                }
            }
        }
        msgs = SECSourceAdapter().convert(facts, AS_OF, security_id="co1")
        rev_msgs = [m for m in msgs if m.payload.get("field") == "revenue"]
        assert len(rev_msgs) == 2
        revisions = sorted(m.payload["revision"] for m in rev_msgs)
        assert revisions == [0, 1]
        revision_types = {m.payload["revision"]: m.msg_type for m in rev_msgs}
        assert revision_types[0] == MessageType.OBSERVATION
        assert revision_types[1] == MessageType.REVISION

    def test_cik_fallback_security_id(self):
        facts = _apple_company_facts()
        msgs = SECSourceAdapter().convert(facts, AS_OF)  # no security_id kwarg
        assert all(m.payload["id"].startswith("cik:") for m in msgs)

    def test_fingerprint_stable(self):
        facts = _apple_company_facts()
        m1 = SECSourceAdapter().convert(facts, AS_OF, security_id="aapl")[0]
        m2 = SECSourceAdapter().convert(facts, AS_OF, security_id="aapl")[0]
        assert m1.raw_fingerprint() == m2.raw_fingerprint()

    def test_fetch_raises(self):
        with pytest.raises(NotImplementedError):
            SECSourceAdapter().fetch(AS_OF)


# ── FRED adapter ──────────────────────────────────────────────────────────────

def _gdp_observations():
    return [
        # original print — released 2024-04-30, for period 2024-01-01
        {"realtime_start": "2024-04-30", "realtime_end": "2024-06-14",
         "date": "2024-01-01", "value": "27357.0"},
        # revision — released 2024-06-14 (before AS_OF=2024-06-30)
        {"realtime_start": "2024-06-14", "realtime_end": "9999-12-31",
         "date": "2024-01-01", "value": "27380.5"},
    ]


class TestFREDAdapter:
    def test_basic_conversion(self):
        obs = [{"date": "2024-01-01", "value": "5.25", "realtime_start": "2024-01-31"}]
        msgs = FREDSourceAdapter().convert(obs, "FEDFUNDS", AS_OF)
        assert len(msgs) == 1
        assert msgs[0].payload["field"] == "fed_funds_rate"
        assert msgs[0].payload["value"] == 5.25

    def test_release_date_is_observation_date(self):
        obs = _gdp_observations()
        msgs = FREDSourceAdapter().convert(obs, "GDP", AS_OF)
        # first message: realtime_start=2024-04-30
        first = next(m for m in msgs if m.payload["revision"] == 0)
        assert first.observation_date == date(2024, 4, 30)
        assert first.effective_date == date(2024, 1, 1)

    def test_vintage_revision_numbering(self):
        msgs = FREDSourceAdapter().convert(_gdp_observations(), "GDP", AS_OF)
        revisions = sorted(m.payload["revision"] for m in msgs)
        assert revisions == [0, 1]

    def test_revision_message_type(self):
        msgs = FREDSourceAdapter().convert(_gdp_observations(), "GDP", AS_OF)
        rev_msgs = {m.payload["revision"]: m.msg_type for m in msgs}
        assert rev_msgs[0] == MessageType.OBSERVATION
        assert rev_msgs[1] == MessageType.REVISION

    def test_future_observation_rejected(self):
        obs = [{"realtime_start": FUTURE.isoformat(), "date": "2025-01-01", "value": "28000"}]
        msgs = FREDSourceAdapter().convert(obs, "GDP", AS_OF)
        assert len(msgs) == 0

    def test_missing_value_sentinel(self):
        obs = [{"date": "2024-01-01", "value": ".", "realtime_start": "2024-02-01"}]
        msgs = FREDSourceAdapter().convert(obs, "GDP", AS_OF)
        assert len(msgs) == 0

    def test_unknown_series_uses_lowercase_id(self):
        obs = [{"date": "2024-01-01", "value": "42", "realtime_start": "2024-02-01"}]
        msgs = FREDSourceAdapter().convert(obs, "MYINDICATOR", AS_OF)
        assert msgs[0].payload["field"] == "myindicator"

    def test_fingerprint_stable(self):
        obs = [{"date": "2024-01-01", "value": "5.25", "realtime_start": "2024-01-31"}]
        m1 = FREDSourceAdapter().convert(obs, "FEDFUNDS", AS_OF)[0]
        m2 = FREDSourceAdapter().convert(obs, "FEDFUNDS", AS_OF)[0]
        assert m1.raw_fingerprint() == m2.raw_fingerprint()


# ── India adapter ─────────────────────────────────────────────────────────────

class TestIndiaAdapter:
    def _nse_record(self, symbol="RELIANCE", d=None, close=2500.0):
        return {"SYMBOL": symbol, "TIMESTAMP": (d or AS_OF).isoformat(),
                "OPEN": 2490.0, "HIGH": 2510.0, "LOW": 2485.0, "CLOSE": close,
                "TOTTRDQTY": 1_500_000, "ISIN": "INE002A01018"}

    def _bse_record(self, code="500325", d=None, close=2500.0):
        return {"Code": code, "Name": "Reliance Industries",
                "Date": (d or AS_OF).isoformat(),
                "Open": 2490.0, "High": 2510.0, "Low": 2485.0,
                "Close": close, "Volume": 1_500_000}

    def test_nse_conversion(self):
        msgs = IndiaSourceAdapter().convert_nse([self._nse_record()], AS_OF)
        assert len(msgs) == 1
        assert msgs[0].payload["currency"] == "INR"
        assert msgs[0].payload["exchange"] == "NSE"
        assert msgs[0].payload["value"] == 2500.0

    def test_bse_conversion(self):
        msgs = IndiaSourceAdapter().convert_bse([self._bse_record()], AS_OF)
        assert len(msgs) == 1
        assert msgs[0].payload["exchange"] == "BSE"

    def test_macro_conversion(self):
        rec = {"indicator": "CPI", "date": AS_OF.isoformat(), "value": 5.2, "unit": "percent"}
        msgs = IndiaSourceAdapter().convert_macro([rec], AS_OF)
        assert len(msgs) == 1
        assert msgs[0].payload["country"] == "IN"

    def test_nse_future_rejected(self):
        msgs = IndiaSourceAdapter().convert_nse([self._nse_record(d=FUTURE)], AS_OF)
        assert len(msgs) == 0

    def test_nse_isin_in_payload(self):
        msgs = IndiaSourceAdapter().convert_nse([self._nse_record()], AS_OF)
        assert msgs[0].payload.get("isin") == "INE002A01018"

    def test_id_map_isin_resolution(self):
        from mentisrex.research.market_data.identifiers import IdType, IdentifierMap
        id_map = IdentifierMap()
        id_map.add(IdType.ISIN, "INE002A01018", "reliance_internal")
        adapter = IndiaSourceAdapter(id_map=id_map)
        msgs = adapter.convert_nse([self._nse_record()], AS_OF)
        assert msgs[0].payload["id"] == "reliance_internal"

    def test_date_format_ddmmyyyy(self):
        rec = self._nse_record()
        rec["TIMESTAMP"] = "30/06/2024"  # alternative date format
        msgs = IndiaSourceAdapter().convert_nse([rec], AS_OF)
        assert len(msgs) == 1

    def test_fetch_raises(self):
        with pytest.raises(NotImplementedError):
            IndiaSourceAdapter().fetch(AS_OF)


# ── Qlib adapter & exporter ───────────────────────────────────────────────────

_QLIB_CSV = """\
date,open,high,low,close,volume,factor,change
2024-01-02,188.5,189.0,187.0,188.0,52000000,1.0,0.01
2024-01-03,188.0,190.0,187.5,189.5,48000000,1.0,0.008
2024-06-28,210.0,212.0,209.0,211.0,30000000,1.02,0.005
"""


class TestQlibAdapter:
    def test_csv_conversion(self):
        msgs = QlibSourceAdapter().convert_csv(_QLIB_CSV, "AAPL", AS_OF)
        assert len(msgs) >= 3  # at least close per row; factor=1.02 adds adj_close for last row

    def test_factor_generates_adj_close(self):
        msgs = QlibSourceAdapter().convert_csv(_QLIB_CSV, "AAPL", AS_OF)
        adj_msgs = [m for m in msgs if m.payload.get("type") == "adjusted_close"]
        assert len(adj_msgs) >= 1  # the row with factor=1.02 should generate adj_close

    def test_future_rows_rejected(self):
        csv_text = "date,open,high,low,close,volume,factor,change\n"
        csv_text += f"{FUTURE.isoformat()},100,105,99,103,1000000,1.0,0.01\n"
        msgs = QlibSourceAdapter().convert_csv(csv_text, "X", AS_OF)
        assert len(msgs) == 0

    def test_fingerprint_stable(self):
        m1 = QlibSourceAdapter().convert_csv(_QLIB_CSV, "AAPL", AS_OF)[0]
        m2 = QlibSourceAdapter().convert_csv(_QLIB_CSV, "AAPL", AS_OF)[0]
        assert m1.raw_fingerprint() == m2.raw_fingerprint()


class TestQlibExporter:
    def _observations(self):
        from mentisrex.research.market_data.models import CanonicalObservation, ObservationType, Unit
        obs = []
        for i in range(3):
            d = date(2024, 1, 2 + i)
            for field, val in [("close", 150.0 + i), ("open", 149.0 + i),
                                ("high", 152.0 + i), ("low", 148.0 + i), ("volume", 5e7)]:
                obs.append(CanonicalObservation(
                    security_id="AAPL", obs_type=ObservationType.CLOSE,
                    field=field, value=val,
                    observation_date=d, effective_date=d,
                    unit=Unit.PRICE if field != "volume" else Unit.SHARES,
                ))
        return obs

    def test_export_creates_csv(self, tmp_path):
        obs = self._observations()
        written = QlibExporter().export(obs, tmp_path)
        assert "AAPL" in written
        assert written["AAPL"].exists()
        content = written["AAPL"].read_text()
        assert "date" in content and "close" in content

    def test_export_deterministic(self, tmp_path):
        obs = self._observations()
        p1 = tmp_path / "e1"
        p2 = tmp_path / "e2"
        QlibExporter().export(obs, p1)
        QlibExporter().export(obs, p2)
        assert (p1 / "AAPL.csv").read_text() == (p2 / "AAPL.csv").read_text()


# ── FinanceToolkit adapter ────────────────────────────────────────────────────

class TestFinanceToolkitAdapter:
    def _record(self, symbol="AAPL", close_date="2022-09-24", filed="2022-10-28"):
        return {
            "symbol": symbol, "date": close_date, "filed": filed,
            "revenue": 394328000000, "gross_profit": 170782000000,
            "operating_income": 119437000000, "net_income": 99803000000,
            "total_assets": 352755000000, "stockholders_equity": 50672000000,
            "currency": "USD",
        }

    def test_emits_multiple_fields(self):
        msgs = FinanceToolkitSourceAdapter().convert([self._record()], AS_OF)
        fields = {m.payload["field"] for m in msgs}
        assert "revenue" in fields and "net_income" in fields

    def test_pit_filed_is_observation_date(self):
        msgs = FinanceToolkitSourceAdapter().convert([self._record()], AS_OF)
        revenue_msg = next(m for m in msgs if m.payload["field"] == "revenue")
        assert revenue_msg.observation_date == date(2022, 10, 28)

    def test_future_filing_rejected(self):
        r = self._record(filed=FUTURE.isoformat())
        msgs = FinanceToolkitSourceAdapter().convert([r], AS_OF)
        assert len(msgs) == 0

    def test_currency_in_payload(self):
        msgs = FinanceToolkitSourceAdapter().convert([self._record()], AS_OF)
        assert all(m.payload.get("currency") == "USD" for m in msgs)


# ── Fundamental ratio engine ──────────────────────────────────────────────────

class TestFundamentalRatioEngine:
    def _fields(self):
        return {
            "revenue": 394328e6, "gross_profit": 170782e6,
            "operating_income": 119437e6, "net_income": 99803e6,
            "ebitda": 130541e6, "total_assets": 352755e6,
            "stockholders_equity": 50672e6, "long_term_debt": 98959e6,
            "current_assets": 135405e6, "current_liabilities": 153982e6,
            "cash": 23646e6, "shares_outstanding": 16_325_819_000,
            "eps_diluted": 6.11, "cash_flow_operations": 122151e6, "capex": 10708e6,
        }

    def test_gross_margin(self):
        engine = FundamentalRatioEngine()
        ratios = engine.compute("aapl", self._fields(), date(2022, 10, 28), date(2022, 9, 24))
        gm = next(r for r in ratios if r.ratio_name == "gross_margin")
        assert abs(gm.value - 170782e6 / 394328e6) < 1e-6

    def test_net_margin(self):
        ratios = FundamentalRatioEngine().compute(
            "aapl", self._fields(), date(2022, 10, 28), date(2022, 9, 24))
        nm = next(r for r in ratios if r.ratio_name == "net_margin")
        assert abs(nm.value - 99803e6 / 394328e6) < 1e-6

    def test_pe_ratio_with_price(self):
        ratios = FundamentalRatioEngine().compute(
            "aapl", self._fields(), date(2022, 10, 28), date(2022, 9, 24), price=150.0)
        pe = next(r for r in ratios if r.ratio_name == "pe_ratio")
        assert abs(pe.value - 150.0 / 6.11) < 0.01

    def test_zero_denominator_returns_no_ratio(self):
        fields = {"revenue": 0.0, "net_income": 100.0}
        ratios = FundamentalRatioEngine().compute("x", fields, AS_OF, AS_OF)
        ratio_names = {r.ratio_name for r in ratios}
        # net_margin = net_income / revenue; revenue=0 → must NOT appear
        assert "net_margin" not in ratio_names

    def test_fundamental_observation_valid(self):
        ratios = FundamentalRatioEngine().compute(
            "aapl", self._fields(), date(2022, 10, 28), date(2022, 9, 24))
        assert all(r.valid for r in ratios)

    def test_growth_ratios(self):
        current = {"revenue": 400e9, "net_income": 100e9}
        prior = {"revenue": 360e9, "net_income": 90e9}
        ratios = FundamentalRatioEngine().compute_growth(
            "aapl", current, prior, AS_OF, AS_OF)
        rev_growth = next(r for r in ratios if r.ratio_name == "revenue_growth")
        assert abs(rev_growth.value - (400e9 - 360e9) / 360e9) < 1e-9

    def test_inputs_preserved_in_observation(self):
        ratios = FundamentalRatioEngine().compute(
            "aapl", self._fields(), date(2022, 10, 28), date(2022, 9, 24))
        gm = next(r for r in ratios if r.ratio_name == "gross_margin")
        assert "gross_profit" in gm.inputs and "revenue" in gm.inputs

    def test_provenance_fields(self):
        ratios = FundamentalRatioEngine().compute(
            "aapl", self._fields(), date(2022, 10, 28), date(2022, 9, 24))
        r = ratios[0]
        assert r.security_id == "aapl"
        assert r.observation_date == date(2022, 10, 28)
        assert r.effective_date == date(2022, 9, 24)


# ── Lean exporter ─────────────────────────────────────────────────────────────

class TestLeanExporter:
    def _observations(self):
        from mentisrex.research.market_data.models import CanonicalObservation, ObservationType, Unit
        obs = []
        for i in range(5):
            d = date(2024, 1, 2 + i)
            for field, val in [("close", 150.0 + i), ("open", 149.0 + i),
                                ("high", 152.0 + i), ("low", 148.0 + i), ("volume", 5e7)]:
                obs.append(CanonicalObservation(
                    security_id="AAPL", obs_type=ObservationType.CLOSE,
                    field=field, value=val, observation_date=d, effective_date=d,
                    unit=Unit.PRICE,
                ))
        return obs

    def test_ohlcv_export_creates_zip(self, tmp_path):
        written = LeanExporter().export_ohlcv(self._observations(), tmp_path)
        assert "AAPL" in written
        assert written["AAPL"].exists()
        assert written["AAPL"].suffix == ".zip"

    def test_ohlcv_values_scaled_to_10000ths(self, tmp_path):
        import zipfile
        written = LeanExporter().export_ohlcv(self._observations(), tmp_path)
        with zipfile.ZipFile(written["AAPL"]) as zf:
            content = zf.read(zf.namelist()[0]).decode()
        # first row close = 150.0 → 1500000
        assert "1500000" in content

    def test_universe_export(self, tmp_path):
        universe = {date(2024, 1, 2): ["AAPL", "MSFT"], date(2024, 1, 3): ["AAPL"]}
        path = LeanExporter().export_universe(universe, tmp_path / "universe.csv")
        content = path.read_text()
        assert "AAPL" in content and "MSFT" in content

    def test_signals_export(self, tmp_path):
        signals = [
            {"date": date(2024, 1, 2), "ticker": "AAPL", "signal_name": "momentum", "value": 0.8},
            {"date": date(2024, 1, 2), "ticker": "MSFT", "signal_name": "momentum", "value": 0.6},
        ]
        path = LeanExporter().export_signals(signals, tmp_path / "signals.csv")
        content = path.read_text()
        assert "momentum" in content

    def test_targets_export(self, tmp_path):
        targets = [
            {"date": date(2024, 1, 2), "ticker": "AAPL", "weight": 0.6},
            {"date": date(2024, 1, 2), "ticker": "MSFT", "weight": 0.4},
        ]
        path = LeanExporter().export_targets(targets, tmp_path / "targets.csv")
        content = path.read_text()
        assert "0.6" in content and "0.4" in content

    def test_export_deterministic(self, tmp_path):
        obs = self._observations()
        w1 = LeanExporter().export_ohlcv(obs, tmp_path / "r1")
        w2 = LeanExporter().export_ohlcv(obs, tmp_path / "r2")
        import zipfile
        with zipfile.ZipFile(w1["AAPL"]) as z1, zipfile.ZipFile(w2["AAPL"]) as z2:
            assert z1.read(z1.namelist()[0]) == z2.read(z2.namelist()[0])


# ── Integration: Provider → M20 → M19 → M18 snapshot ─────────────────────────

class TestFullPipeline:
    """Exercise the full pipeline: provider adapter → M20 MessageLogAdapter → M19 normalizer
    → M19 snapshot builder → M18 MarketDataSnapshot."""

    def test_yahoo_to_snapshot(self):
        yahoo = YahooFinanceSourceAdapter()
        records = [
            {"symbol": "S1", "date": "2024-06-28", "close": 100.0, "open": 99.0,
             "high": 101.0, "low": 98.0, "volume": 1e6},
            {"symbol": "S2", "date": "2024-06-28", "close": 200.0, "open": 198.0,
             "high": 202.0, "low": 197.0, "volume": 5e5},
        ]
        msgs = yahoo.convert(records, AS_OF)
        assert len(msgs) >= 2

        # route through M20 MessageLogAdapter
        adapter = MessageLogAdapter(msgs, name="yahoo_fixture")
        adapter.connect()
        fetched = adapter.fetch(AS_OF)
        assert len(fetched) >= 2

        # extract payloads for M19 normalizer
        raw = [m.payload for m in fetched if m.msg_type == MessageType.OBSERVATION]
        normalizer = Normalizer()
        result = normalizer.normalize(raw, as_of=AS_OF)
        assert result.ok
        canon = result.observations
        assert len(canon) >= 2

        # verify PIT safety: no observation_date > AS_OF
        for obs in canon:
            assert obs.observation_date <= AS_OF

        # build M18 snapshot
        builder = MarketDataSnapshotBuilder()
        build = builder.build(as_of=AS_OF, raw=raw)
        snap = build.snapshot
        assert snap is not None
        assert snap.as_of == AS_OF

    def test_fred_pit_reconstruction_via_revision_store(self):
        from mentisrex.research.market_data.revisions import RevisionStore
        fred = FREDSourceAdapter()
        obs = [
            {"realtime_start": "2024-04-30", "date": "2024-01-01", "value": "27357.0"},
            {"realtime_start": "2024-06-14", "date": "2024-01-01", "value": "27380.5"},
        ]
        msgs = fred.convert(obs, "GDP", AS_OF)

        store = RevisionStore()
        for m in msgs:
            store.record(
                m.payload["id"], m.payload["field"],
                m.effective_date, m.payload["value"],
                knowledge_date=m.observation_date,
                source=m.source,
            )

        # on 2024-04-30, only the first print was known
        as_of_april = date(2024, 4, 30)
        r = store.known_as_of("GDP", "gdp", date(2024, 1, 1), as_of_april)
        assert r is not None
        assert r.value == 27357.0

        # on 2024-06-14, the revision is visible
        r_revised = store.known_as_of("GDP", "gdp", date(2024, 1, 1), date(2024, 6, 14))
        assert r_revised.value == 27380.5

    def test_no_provider_leakage_through_source_message(self):
        """SourceMessage payload must not contain non-serialisable provider objects."""
        import json
        msgs = OpenBBSourceAdapter().convert(
            [{"symbol": "X", "date": AS_OF.isoformat(), "close": 10.0}], AS_OF)
        for m in msgs:
            json.dumps(m.payload, default=str)  # must not raise

    def test_identical_input_identical_fingerprint(self):
        """Idempotency: same input records → same SourceMessage fingerprints."""
        records = [{"symbol": f"S{i}", "date": AS_OF.isoformat(), "close": float(100 + i)}
                   for i in range(5)]
        fps1 = [m.raw_fingerprint() for m in OpenBBSourceAdapter().convert(records, AS_OF)]
        fps2 = [m.raw_fingerprint() for m in OpenBBSourceAdapter().convert(records, AS_OF)]
        assert fps1 == fps2


# ── Benchmarks ────────────────────────────────────────────────────────────────

def _make_equity_records(n: int, adapter_name: str = "openbb") -> list[dict]:
    base = date(2020, 1, 1)
    from datetime import timedelta
    records = []
    for i in range(n):
        d = base + timedelta(days=i % 1000)
        symbol = f"S{i % 500:04d}"
        records.append({
            "symbol": symbol, "date": d.isoformat(),
            "open": 100.0 + (i % 50), "high": 105.0 + (i % 50),
            "low": 98.0 + (i % 50), "close": 101.0 + (i % 50),
            "volume": float(1_000_000 + i),
        })
    return records


@pytest.mark.slow
def test_benchmark_100k_observations():
    records = _make_equity_records(100_000)
    adapter = OpenBBSourceAdapter()
    t0 = time.perf_counter()
    msgs = adapter.convert(records, date(2023, 12, 31))
    elapsed = time.perf_counter() - t0
    assert len(msgs) == 100_000
    assert elapsed < 10.0, f"100k conversion took {elapsed:.2f}s, target <10s"


@pytest.mark.slow
def test_benchmark_1m_observations():
    records = _make_equity_records(1_000_000)
    adapter = OpenBBSourceAdapter()
    t0 = time.perf_counter()
    msgs = adapter.convert(records, date(2023, 12, 31))
    elapsed = time.perf_counter() - t0
    assert len(msgs) == 1_000_000
    assert elapsed < 120.0, f"1M conversion took {elapsed:.2f}s, target <2min"
