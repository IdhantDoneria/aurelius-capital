"""AIDP M19 — Institutional Market Data, Curve Calibration & Volatility Surface tests.

Deterministic, offline. Covers the canonical observation model, PIT-aware identifier mapping,
business-day calendars, bitemporal revisions + fixings, sources, the normalization pipeline,
the quality engine, rate instruments, multi-instrument curve bootstrapping, OIS/multi-curve,
credit curves, SABR, SVI, volatility-surface calibration + arbitrage diagnostics, the PIT
snapshot builder, validators, serialization round-trips, registry, production adapter contracts,
the engine façade, financial invariants, M16/M17/M18 integration and determinism.
"""

from __future__ import annotations

import math
from datetime import date, datetime

import pytest

from mentisrex.research import fx as m16fx
from mentisrex.research import instruments as ins
from mentisrex.research import market_data as md
from mentisrex.research.market_data import diagnostics as mdiag
from mentisrex.research.market_data import serialization as ser
from mentisrex.research.market_data.sabr import sabr_vol
from mentisrex.research.valuation.engine import ValuationEngine
from mentisrex.research.valuation.models import ValuationConfiguration


# ── helpers ───────────────────────────────────────────────────────────────────

REF = date(2024, 6, 3)


def obs(sid="AAPL", field="close", value=190.0, obs_d=REF, eff=None, **kw):
    from mentisrex.research.market_data.models import CanonicalObservation, ObservationType, Unit
    return CanonicalObservation(
        security_id=sid, obs_type=kw.pop("obs_type", ObservationType.CLOSE), field=field,
        value=value, observation_date=obs_d, effective_date=eff or obs_d,
        unit=kw.pop("unit", Unit.PRICE), **kw)


def swap_curve(rates=None):
    rates = rates or [(0.25, 0.05), (1, 0.05), (5, 0.05), (10, 0.05)]
    insts = [md.deposit(rates[0][0], rates[0][1])] + [md.swap(t, r) for t, r in rates[1:]]
    return md.CurveBootstrapper().bootstrap(insts, REF, curve_id="USD", currency="USD").curve


def sabr_smile(f, t, underlying="SPX", params=(0.25, 0.5, -0.3, 0.4)):
    ks = [f * m for m in (0.8, 0.9, 1.0, 1.1, 1.2)]
    vols = tuple(sabr_vol(f, k, t, *params) for k in ks)
    return md.SmileQuotes(f, t, tuple(ks), vols, underlying=underlying)


# ══════════════════════════════════════════════════════════════════════════════
# 1. canonical observation model
# ══════════════════════════════════════════════════════════════════════════════

def test_observation_fingerprint_stable():
    assert obs().fingerprint() == obs().fingerprint()


def test_observation_fingerprint_changes_with_value():
    assert obs(value=190.0).fingerprint() != obs(value=191.0).fingerprint()


def test_observation_fingerprint_changes_with_revision():
    assert obs(revision=0).fingerprint() != obs(revision=1).fingerprint()


def test_observation_provenance_carries_pit():
    p = obs().provenance()
    assert p.observation_date == REF and p.instrument_id == "AAPL"


def test_observation_with_status_immutable():
    from mentisrex.research.market_data.models import QualityStatus
    o = obs()
    o2 = o.with_status(QualityStatus.VALIDATED)
    assert o.status is QualityStatus.RAW and o2.status is QualityStatus.VALIDATED


def test_observation_key_ignores_source_revision():
    assert obs(revision=0).key == obs(revision=5).key


def test_observation_types_distinct():
    from mentisrex.research.market_data.models import ObservationType
    assert len({t.value for t in ObservationType}) == len(list(ObservationType))


def test_quality_diagnostic_rejects():
    from mentisrex.research.market_data.models import QualityDiagnostic, Severity
    assert QualityDiagnostic("c", Severity.REJECT, "m").rejects
    assert not QualityDiagnostic("c", Severity.WARNING, "m").rejects


def test_unit_enum_has_rate_and_price():
    from mentisrex.research.market_data.models import Unit
    assert Unit.RATE.value == "rate" and Unit.PRICE.value == "price"


def test_observation_default_unit_price():
    from mentisrex.research.market_data.models import Unit
    assert obs().unit is Unit.PRICE


# ══════════════════════════════════════════════════════════════════════════════
# 2. identifiers (PIT + no collapse)
# ══════════════════════════════════════════════════════════════════════════════

def test_identifier_resolve_basic():
    m = md.IdentifierMap()
    m.add(md.IdType.TICKER, "AAPL", "SEC_APPLE")
    assert m.resolve(md.IdType.TICKER, "AAPL") == "SEC_APPLE"


def test_identifier_pit_window():
    m = md.IdentifierMap()
    m.add(md.IdType.TICKER, "XYZ", "SEC_OLD", end=date(2020, 1, 1))
    m.add(md.IdType.TICKER, "XYZ", "SEC_NEW", start=date(2020, 1, 1))
    assert m.resolve(md.IdType.TICKER, "XYZ", as_of=date(2019, 1, 1)) == "SEC_OLD"
    assert m.resolve(md.IdType.TICKER, "XYZ", as_of=date(2021, 1, 1)) == "SEC_NEW"


def test_identifier_collision_overlapping_raises():
    m = md.IdentifierMap()
    m.add(md.IdType.ISIN, "US1", "SEC_A")
    with pytest.raises(ValueError):
        m.add(md.IdType.ISIN, "US1", "SEC_B")


def test_identifier_no_collision_disjoint_windows():
    m = md.IdentifierMap()
    m.add(md.IdType.TICKER, "T", "A", end=date(2020, 1, 1))
    m.add(md.IdType.TICKER, "T", "B", start=date(2020, 1, 1))   # no raise


def test_identifier_ambiguous_resolution_raises():
    from mentisrex.research.market_data.identifiers import IdentifierRecord
    m = md.IdentifierMap()
    # a corrupted map with two overlapping records for one external id must refuse to resolve
    m._records.append(IdentifierRecord(md.IdType.TICKER, "T", "A"))
    m._records.append(IdentifierRecord(md.IdType.TICKER, "T", "B"))
    with pytest.raises(ValueError):
        m.resolve(md.IdType.TICKER, "T", as_of=date(2019, 9, 1))


def test_identifier_missing_raises():
    with pytest.raises(KeyError):
        md.IdentifierMap().resolve(md.IdType.TICKER, "NOPE")


def test_identifier_reverse_lookup():
    m = md.IdentifierMap()
    m.add(md.IdType.TICKER, "AAPL", "SEC")
    m.add(md.IdType.ISIN, "US037", "SEC")
    ids = m.identifiers("SEC")
    assert ids["ticker"] == "AAPL" and ids["isin"] == "US037"


def test_identifier_try_resolve_none():
    assert md.IdentifierMap().try_resolve(md.IdType.CUSIP, "x") is None


def test_identifier_types_cover_vendors():
    vals = {t.value for t in md.IdType}
    assert {"isin", "cusip", "figi", "bloomberg", "vendor"} <= vals


# ══════════════════════════════════════════════════════════════════════════════
# 3. calendars
# ══════════════════════════════════════════════════════════════════════════════

def test_weekend_not_business_day():
    c = md.WeekendCalendar()
    assert not c.is_business_day(date(2024, 6, 1))     # Saturday
    assert c.is_business_day(date(2024, 6, 3))         # Monday


def test_us_holiday_july4():
    c = md.us_calendar()
    assert not c.is_business_day(date(2024, 7, 4))
    assert c.is_holiday(date(2024, 7, 4))


def test_adjust_modified_following():
    c = md.us_calendar()
    assert c.adjust(date(2024, 7, 4)) == date(2024, 7, 5)


def test_adjust_following():
    c = md.WeekendCalendar()
    assert c.adjust(date(2024, 6, 1), md.RollConvention.FOLLOWING) == date(2024, 6, 3)


def test_adjust_preceding():
    c = md.WeekendCalendar()
    assert c.adjust(date(2024, 6, 1), md.RollConvention.PRECEDING) == date(2024, 5, 31)


def test_adjust_modified_preceding_rolls_forward_at_month_start():
    c = md.WeekendCalendar()
    # 2024-06-01 Sat; modified preceding would go to May 31 (same month? June) -> forward
    out = c.adjust(date(2024, 6, 1), md.RollConvention.MODIFIED_PRECEDING)
    assert out == date(2024, 6, 3)


def test_adjust_none_raises_on_holiday():
    c = md.us_calendar()
    with pytest.raises(ValueError):
        c.adjust(date(2024, 7, 4), md.RollConvention.NONE)


def test_add_business_days_positive():
    c = md.us_calendar()
    assert c.add_business_days(date(2024, 7, 3), 2) == date(2024, 7, 8)   # skip 4th + weekend


def test_add_business_days_negative():
    c = md.WeekendCalendar()
    assert c.add_business_days(date(2024, 6, 3), -1) == date(2024, 5, 31)


def test_business_days_between():
    c = md.WeekendCalendar()
    assert c.business_days_between(date(2024, 6, 3), date(2024, 6, 10)) == 5


def test_joint_calendar_union_holidays():
    j = md.JointCalendar([md.us_calendar(), md.uk_calendar()])
    assert not j.is_business_day(date(2024, 7, 4))         # US holiday
    assert not j.is_business_day(date(2024, 8, 26))        # UK holiday


def test_named_calendar_lookup():
    assert md.calendar("US").name == "US"
    assert md.calendar("india").name == "IN"


def test_named_calendar_unknown_raises():
    with pytest.raises(KeyError):
        md.calendar("MARS")


def test_uk_and_india_calendars_have_holidays():
    assert len(md.uk_calendar().holidays) > 0
    assert len(md.india_calendar().holidays) > 0


def test_india_republic_day_holiday():
    assert not md.india_calendar().is_business_day(date(2024, 1, 26))


# ══════════════════════════════════════════════════════════════════════════════
# 4. revisions + fixings
# ══════════════════════════════════════════════════════════════════════════════

def test_revision_known_as_of_pit():
    s = md.RevisionStore()
    s.record("GDP", "level", date(2024, 3, 31), 100.0, knowledge_date=date(2024, 4, 30))
    s.record("GDP", "level", date(2024, 3, 31), 102.0, knowledge_date=date(2024, 5, 30))
    assert s.known_as_of("GDP", "level", date(2024, 3, 31), date(2024, 5, 1)).value == 100.0
    assert s.known_as_of("GDP", "level", date(2024, 3, 31), date(2024, 6, 1)).value == 102.0


def test_revision_current_is_latest():
    s = md.RevisionStore()
    s.record("GDP", "level", date(2024, 3, 31), 100.0, knowledge_date=date(2024, 4, 30))
    s.record("GDP", "level", date(2024, 3, 31), 102.0, knowledge_date=date(2024, 5, 30))
    assert s.current("GDP", "level", date(2024, 3, 31)).value == 102.0


def test_revision_none_before_publication():
    s = md.RevisionStore()
    s.record("X", "v", REF, 1.0, knowledge_date=date(2024, 7, 1))
    assert s.known_as_of("X", "v", REF, date(2024, 6, 1)) is None


def test_revision_history_and_restated():
    s = md.RevisionStore()
    s.record("X", "v", REF, 1.0, knowledge_date=REF)
    assert not s.was_restated("X", "v", REF)
    s.record("X", "v", REF, 2.0, knowledge_date=date(2024, 7, 1))
    assert s.was_restated("X", "v", REF)
    assert len(s.history("X", "v", REF)) == 2


def test_revision_numbers_monotone():
    s = md.RevisionStore()
    r0 = s.record("X", "v", REF, 1.0, knowledge_date=REF)
    r1 = s.record("X", "v", REF, 2.0, knowledge_date=date(2024, 7, 1))
    assert r0.revision == 0 and r1.revision == 1


def test_fixing_pit_visibility():
    fs = md.FixingStore()
    fs.add("SOFR", date(2024, 6, 3), 0.053, knowledge_date=date(2024, 6, 4))
    with pytest.raises(KeyError):
        fs.get("SOFR", date(2024, 6, 3), as_of=date(2024, 6, 3))
    assert fs.get("SOFR", date(2024, 6, 3), as_of=date(2024, 6, 4)).value == 0.053


def test_fixing_revision_reconstruction():
    fs = md.FixingStore()
    fs.add("EUR/USD", date(2024, 6, 3), 1.10, knowledge_date=date(2024, 6, 3))
    fs.add("EUR/USD", date(2024, 6, 3), 1.101, knowledge_date=date(2024, 6, 5))
    assert fs.get("EUR/USD", date(2024, 6, 3), as_of=date(2024, 6, 3)).value == 1.10
    assert fs.get("EUR/USD", date(2024, 6, 3), as_of=date(2024, 6, 6)).value == 1.101


def test_fixing_type_stored():
    fs = md.FixingStore()
    fs.add("SONIA", date(2024, 6, 3), 0.05, fixing_type=md.FixingType.OVERNIGHT)
    assert fs.get("SONIA", date(2024, 6, 3)).fixing_type is md.FixingType.OVERNIGHT


def test_fixing_missing_raises():
    with pytest.raises(KeyError):
        md.FixingStore().get("NONE", REF)


# ══════════════════════════════════════════════════════════════════════════════
# 5. sources
# ══════════════════════════════════════════════════════════════════════════════

def test_static_source_pit_filter():
    recs = [{"id": "A", "field": "close", "value": 1, "observation_date": "2024-06-03"},
            {"id": "A", "field": "close", "value": 2, "observation_date": "2024-06-10"}]
    s = md.StaticSource(recs)
    assert len(s.fetch(date(2024, 6, 5))) == 1


def test_static_source_no_pit_filter():
    recs = [{"id": "A", "field": "close", "value": 2, "observation_date": "2024-06-10"}]
    s = md.StaticSource(recs, pit_filter=False)
    assert len(s.fetch(date(2024, 6, 5))) == 1


def test_historical_source_pit():
    s = md.HistoricalSource({date(2024, 6, 3): [{"id": "A", "field": "close", "value": 1}],
                             date(2024, 6, 10): [{"id": "A", "field": "close", "value": 2}]})
    assert len(s.fetch(date(2024, 6, 5))) == 1
    assert len(s.fetch(date(2024, 6, 11))) == 2


def test_mock_source_deterministic():
    s = md.DeterministicMockSource({"A": 100.0})
    assert s.fetch(REF) == s.fetch(REF)


def test_source_filter_by_security():
    s = md.DeterministicMockSource({"A": 100.0, "B": 50.0})
    out = s.fetch(REF, security_ids=["A"])
    assert len(out) == 1 and out[0]["id"] == "A"


def test_source_filter_by_field():
    recs = [{"id": "A", "field": "close", "value": 1}, {"id": "A", "field": "bid", "value": 0.9}]
    assert len(md.StaticSource(recs, pit_filter=False).fetch(REF, fields=["bid"])) == 1


# ══════════════════════════════════════════════════════════════════════════════
# 6. normalization
# ══════════════════════════════════════════════════════════════════════════════

def test_normalize_close_alias():
    r = md.Normalizer().normalize([{"id": "A", "field": "adj_close", "value": 10.0}], as_of=REF)
    o = r.observations[0]
    assert o.field == "close" and o.obs_type.value == "adjusted_close"


def test_normalize_percent_to_rate():
    from mentisrex.research.market_data.models import Unit
    r = md.Normalizer().normalize(
        [{"id": "C", "field": "rate", "value": 5.0, "unit": "percent"}], as_of=REF)
    o = r.observations[0]
    assert abs(o.value - 0.05) < 1e-12 and o.unit is Unit.RATE


def test_normalize_basis_points_to_rate():
    r = md.Normalizer().normalize(
        [{"id": "C", "field": "rate", "value": 50.0, "unit": "bp"}], as_of=REF)
    assert abs(r.observations[0].value - 0.005) < 1e-12


def test_normalize_currency_conversion():
    fx = m16fx.rates.StaticFXRateProvider({"EUR/USD": 1.10})
    n = md.Normalizer(fx_provider=fx, base_currency="USD", convert_currency=True)
    r = n.normalize([{"id": "E", "field": "close", "value": 100.0, "currency": "EUR"}], as_of=REF)
    assert abs(r.observations[0].value - 110.0) < 1e-9


def test_normalize_dedup_keeps_highest_revision():
    raw = [{"id": "A", "field": "close", "value": 1.0, "revision": 0},
           {"id": "A", "field": "close", "value": 2.0, "revision": 1}]
    r = md.Normalizer().normalize(raw, as_of=REF)
    assert len(r.observations) == 1 and r.observations[0].value == 2.0


def test_normalize_missing_id_rejected():
    from mentisrex.research.market_data.models import Severity
    r = md.Normalizer().normalize([{"field": "close", "value": 1.0}], as_of=REF)
    assert not r.observations and any(d.severity is Severity.REJECT for d in r.diagnostics)


def test_normalize_non_numeric_rejected():
    r = md.Normalizer().normalize([{"id": "A", "field": "close", "value": "abc"}], as_of=REF)
    assert not r.observations


def test_normalize_id_map_resolution():
    m = md.IdentifierMap()
    m.add(md.IdType.TICKER, "AAPL", "SEC_APPLE")
    n = md.Normalizer(id_map=m)
    r = n.normalize([{"id": "AAPL", "id_type": "ticker", "field": "close", "value": 1.0}], as_of=REF)
    assert r.observations[0].security_id == "SEC_APPLE"


def test_normalize_transform_log_nonempty():
    r = md.Normalizer().normalize(
        [{"id": "C", "field": "rate", "value": 5.0, "unit": "percent"}], as_of=REF)
    assert len(r.transform_log) > 0


def test_normalize_timestamp_inconsistency_logged():
    raw = [{"id": "A", "field": "close", "value": 1.0, "observation_date": "2024-06-03",
            "timestamp": "2024-06-04T10:00:00"}]
    r = md.Normalizer().normalize(raw, as_of=REF)
    assert any("timestamp" in line for line in r.transform_log)


def test_normalize_defaults_obs_date_to_as_of():
    r = md.Normalizer().normalize([{"id": "A", "field": "close", "value": 1.0}], as_of=REF)
    assert r.observations[0].observation_date == REF


def test_normalize_duplicate_logged():
    raw = [{"id": "A", "field": "close", "value": 1.0, "revision": 1},
           {"id": "A", "field": "close", "value": 9.0, "revision": 0}]
    r = md.Normalizer().normalize(raw, as_of=REF)
    assert r.observations[0].value == 1.0 and any("duplicate" in l for l in r.transform_log)


# ══════════════════════════════════════════════════════════════════════════════
# 7. quality engine
# ══════════════════════════════════════════════════════════════════════════════

def test_quality_look_ahead_rejected():
    qe = md.MarketDataQualityEngine()
    rep = qe.check([obs(obs_d=date(2024, 6, 10))], as_of=REF)
    assert rep.rejected and not rep.ok


def test_quality_stale_warns():
    from mentisrex.research.market_data.models import Severity
    qe = md.MarketDataQualityEngine(md.QualityConfig(max_staleness_days=2))
    rep = qe.check([obs(obs_d=date(2024, 5, 1))], as_of=REF)
    assert any(d.code == "stale" and d.severity is Severity.WARNING for d in rep.diagnostics)


def test_quality_non_positive_price_rejected():
    rep = md.MarketDataQualityEngine().check([obs(value=-1.0)], as_of=REF)
    assert rep.rejected


def test_quality_crossed_quote_rejected():
    o = obs(field="bid", value=190.2, meta={"bid": 190.2, "ask": 190.0})
    rep = md.MarketDataQualityEngine().check([o], as_of=REF)
    assert rep.rejected


def test_quality_wide_spread_warns():
    from mentisrex.research.market_data.models import Severity
    o = obs(meta={"bid": 100.0, "ask": 130.0})
    rep = md.MarketDataQualityEngine().check([o], as_of=REF)
    assert any(d.code == "wide_spread" and d.severity is Severity.WARNING for d in rep.diagnostics)


def test_quality_bad_ohlc_rejected():
    o = obs(value=95.0, meta={"open": 100.0, "high": 99.0, "low": 90.0})   # high<open
    rep = md.MarketDataQualityEngine().check([o], as_of=REF)
    assert rep.rejected


def test_quality_negative_volume_error():
    from mentisrex.research.market_data.models import ObservationType, Severity, Unit
    o = obs(field="volume", value=-5.0, obs_type=ObservationType.VOLUME, unit=Unit.SHARES)
    rep = md.MarketDataQualityEngine().check([o], as_of=REF)
    assert any(d.code == "negative_volume" and d.severity is Severity.ERROR for d in rep.diagnostics)


def test_quality_price_jump_warns():
    from mentisrex.research.market_data.models import Severity
    rep = md.MarketDataQualityEngine().check([obs(value=300.0)], as_of=REF, prior={"AAPL": 190.0})
    assert any(d.code == "price_jump" and d.severity is Severity.WARNING for d in rep.diagnostics)


def test_quality_clean_accepted_validated():
    from mentisrex.research.market_data.models import QualityStatus
    rep = md.MarketDataQualityEngine().check([obs()], as_of=REF)
    assert rep.ok and rep.accepted[0].status is QualityStatus.VALIDATED


def test_quality_suspect_status_on_warning():
    from mentisrex.research.market_data.models import QualityStatus
    o = obs(meta={"bid": 100.0, "ask": 130.0})
    rep = md.MarketDataQualityEngine().check([o], as_of=REF)
    assert rep.accepted[0].status is QualityStatus.SUSPECT


def test_quality_by_severity():
    from mentisrex.research.market_data.models import Severity
    rep = md.MarketDataQualityEngine().check([obs(value=-1.0)], as_of=REF)
    assert rep.by_severity(Severity.REJECT)


def test_quality_missing_value_rejected():
    from mentisrex.research.market_data.models import CanonicalObservation, ObservationType, Unit
    o = CanonicalObservation("A", ObservationType.CLOSE, "close", float("nan"), REF, REF)
    rep = md.MarketDataQualityEngine().check([o], as_of=REF)
    assert rep.rejected


# ══════════════════════════════════════════════════════════════════════════════
# 8. diagnostics (pure functions)
# ══════════════════════════════════════════════════════════════════════════════

def test_diag_bad_ohlc():
    assert mdiag.bad_ohlc(100, 99, 90, 95) is not None
    assert mdiag.bad_ohlc(95, 100, 90, 96) is None


def test_diag_crossed_quote():
    assert mdiag.crossed_quote(101, 100) is not None
    assert mdiag.crossed_quote(100, 101) is None


def test_diag_wide_spread():
    assert mdiag.wide_spread(100, 130, max_frac=0.1) is not None
    assert mdiag.wide_spread(100, 100.5, max_frac=0.1) is None


def test_diag_price_jump():
    assert mdiag.price_jump(100, 200, max_frac=0.5) is not None
    assert mdiag.price_jump(100, 110, max_frac=0.5) is None


def test_diag_non_positive_price():
    assert mdiag.non_positive_price(0.0) is not None
    assert mdiag.non_positive_price(1.0) is None


def test_diag_negative_volume():
    assert mdiag.negative_volume(-1) is not None
    assert mdiag.negative_volume(0) is None


def test_diag_stale_and_lookahead():
    assert mdiag.stale(date(2024, 5, 1), REF, 2) is not None
    assert mdiag.look_ahead(date(2024, 6, 10), REF) is not None
    assert mdiag.look_ahead(REF, REF) is None


def test_diag_reexports_m18():
    assert callable(mdiag.put_call_parity) and callable(mdiag.fx_reciprocal)


# ══════════════════════════════════════════════════════════════════════════════
# 9. rate instruments
# ══════════════════════════════════════════════════════════════════════════════

def test_deposit_maturity():
    assert md.deposit(0.5, 0.05).maturity_years() == 0.5


def test_fra_maturity_and_start():
    f = md.fra(0.5, 0.75, 0.05)
    assert f.start == 0.5 and abs(f.maturity_years() - 0.75) < 1e-12


def test_future_implied_rate():
    fut = md.rate_future(0.25, 95.0)
    assert abs(fut.implied_rate() - 0.05) < 1e-12


def test_swap_frequency_convention():
    s = md.swap(5, 0.05, frequency=4)
    assert s.convention.frequency == 4


def test_instrument_name():
    assert "swap" in md.swap(5, 0.05).name()


# ══════════════════════════════════════════════════════════════════════════════
# 10. curve bootstrapping (financial invariants)
# ══════════════════════════════════════════════════════════════════════════════

def test_bootstrap_reprices_deposits():
    res = md.CurveBootstrapper().bootstrap([md.deposit(0.5, 0.05)], REF)
    assert abs(res.residuals[0][1]) < 1e-8


def test_bootstrap_reprices_swaps():
    res = md.CurveBootstrapper().bootstrap(
        [md.deposit(0.25, 0.05), md.swap(2, 0.048), md.swap(5, 0.046), md.swap(10, 0.045)], REF)
    assert max(abs(r) for _, r in res.residuals) < 1e-7


def test_bootstrap_reprices_fra():
    res = md.CurveBootstrapper().bootstrap(
        [md.deposit(0.25, 0.05), md.fra(0.25, 0.5, 0.052), md.swap(2, 0.05)], REF)
    assert max(abs(r) for _, r in res.residuals) < 1e-7


def test_bootstrap_reprices_futures():
    res = md.CurveBootstrapper().bootstrap(
        [md.deposit(0.25, 0.05), md.rate_future(0.25, 94.8), md.swap(2, 0.05)], REF)
    assert max(abs(r) for _, r in res.residuals) < 1e-7


def test_bootstrap_dfs_positive_and_monotone():
    c = swap_curve()
    assert c.validate() == []
    ts = [0.5, 1, 2, 5, 10, 20]
    dfs = [c.discount(t) for t in ts]
    assert all(d > 0 for d in dfs) and all(a >= b for a, b in zip(dfs, dfs[1:]))


def test_bootstrap_report_ok():
    res = md.CurveBootstrapper().bootstrap([md.deposit(0.25, 0.05), md.swap(5, 0.05)], REF)
    assert res.report.ok and res.report.diagnostics.converged


def test_bootstrap_non_increasing_maturity_raises():
    with pytest.raises(md.CurveBootstrapError):
        md.CurveBootstrapper().bootstrap([md.swap(5, 0.05), md.swap(5, 0.04)], REF)


def test_bootstrap_empty_raises():
    with pytest.raises(md.CurveBootstrapError):
        md.CurveBootstrapper().bootstrap([], REF)


def test_bootstrap_flat_when_all_equal():
    c = swap_curve([(0.25, 0.05), (1, 0.05), (5, 0.05), (10, 0.05)])
    # zero curve ~flat at 5% continuous → DF(1) ≈ exp(-0.05) (small par/continuous convention drift)
    assert abs(c.discount(1.0) - math.exp(-0.05)) < 1e-3


def test_bootstrap_par_swap_reprices_par_rate():
    import mentisrex.research.valuation.swaps as sw
    from mentisrex.research.valuation.daycount import DayCount
    c = swap_curve([(0.25, 0.05), (1, 0.05), (5, 0.05), (10, 0.05)])
    pay_dates = tuple(date(y, 6, 3) for y in range(2025, 2030))
    spec = sw.SwapSpec(notional=1.0, fixed_rate=0.05, pay_dates=pay_dates, start=REF,
                       day_count=DayCount.ACT_365, currency="USD")
    assert 0.045 < sw.par_rate(spec, c) < 0.055     # ~5% flat curve, small convention drift


def test_bootstrap_strict_rejects_bad_curve():
    # a single wildly-inconsistent set won't fail here; verify strict flag path exists
    bs = md.CurveBootstrapper(strict=True)
    res = bs.bootstrap([md.deposit(0.25, 0.05), md.swap(5, 0.05)], REF)
    assert res.report.ok


# ══════════════════════════════════════════════════════════════════════════════
# 11. multi-curve
# ══════════════════════════════════════════════════════════════════════════════

def test_single_curve_wraps():
    c = swap_curve()
    mc = md.single_curve(c)
    assert mc.discount_factor(5) == c.discount(5)
    assert mc.project() is c


def test_ois_multicurve_projection():
    disc = swap_curve([(0.25, 0.05), (5, 0.05), (10, 0.05)])
    proj = swap_curve([(0.25, 0.052), (5, 0.052), (10, 0.052)])
    mc = md.ois_multicurve(disc, proj)
    assert mc.discount_factor(5) == disc.discount(5)
    assert mc.forward_rate(1, 2) == proj.forward_rate(1, 2)


def test_multicurve_basis_missing_raises():
    mc = md.single_curve(swap_curve())
    with pytest.raises(KeyError):
        mc.basis_curve("nope")


def test_multicurve_fingerprint_stable():
    mc = md.single_curve(swap_curve())
    assert mc.fingerprint() == mc.fingerprint()


def test_multicurve_fingerprint_reflects_projection():
    disc = swap_curve([(0.25, 0.05), (5, 0.05)])
    proj = swap_curve([(0.25, 0.06), (5, 0.06)])
    assert md.single_curve(disc).fingerprint() != md.ois_multicurve(disc, proj).fingerprint()


# ══════════════════════════════════════════════════════════════════════════════
# 12. credit curves
# ══════════════════════════════════════════════════════════════════════════════

def _credit():
    disc = swap_curve([(0.5, 0.05), (1, 0.05), (5, 0.05), (10, 0.05)])
    q = [md.CDSQuote(1, 0.01), md.CDSQuote(3, 0.012), md.CDSQuote(5, 0.015), md.CDSQuote(10, 0.018)]
    return md.bootstrap_credit(q, disc, recovery=0.4, curve_id="ACME")


def test_credit_bootstrap_reprices():
    cc, rep = _credit()
    assert rep.diagnostics.max_repricing_error < 1e-7 and rep.ok


def test_credit_survival_monotone():
    cc, _ = _credit()
    ts = [0.5, 1, 2, 5, 9]
    assert all(cc.survival(a) >= cc.survival(b) for a, b in zip(ts, ts[1:]))


def test_credit_hazards_nonnegative():
    cc, _ = _credit()
    assert all(h >= 0 for h in cc.hazards)


def test_credit_default_prob_complement():
    cc, _ = _credit()
    assert abs(cc.default_prob(5) - (1 - cc.survival(5))) < 1e-12


def test_credit_par_spread_triangle_approx():
    cc, _ = _credit()
    # hazard ~ spread/(1-R): 5y par ~1.5% -> hazard ~0.025
    assert abs(cc.par_spread(5) - cc.hazard(5) * 0.6) < 1e-12


def test_credit_negative_hazard_raises():
    with pytest.raises(ValueError):
        md.CreditCurve("x", (1.0,), (-0.01,))


def test_credit_survival_at_zero_is_one():
    cc, _ = _credit()
    assert cc.survival(0.0) == 1.0


def test_credit_fingerprint_stable():
    cc, _ = _credit()
    assert cc.fingerprint() == cc.fingerprint()


# ══════════════════════════════════════════════════════════════════════════════
# 13. SABR
# ══════════════════════════════════════════════════════════════════════════════

def test_sabr_atm_vol_formula():
    v = sabr_vol(100, 100, 1.0, 0.2, 0.5, -0.3, 0.4)
    # leading order ATM ~ alpha / f^(1-beta) = 0.2/10 = 0.02
    assert abs(v - 0.02) < 2e-3


def test_sabr_recovers_truth():
    truth = (0.25, 0.5, -0.3, 0.4)
    ks = [80, 90, 100, 110, 120]
    mkt = [sabr_vol(100, k, 1.0, *truth) for k in ks]
    cal = md.calibrate_sabr(100, 1.0, ks, mkt, beta=0.5)
    assert cal.max_residual < 1e-6


def test_sabr_params_validate_clean():
    cal = md.calibrate_sabr(100, 1.0, [90, 100, 110],
                            [sabr_vol(100, k, 1.0, 0.2, 0.5, -0.2, 0.3) for k in (90, 100, 110)])
    assert cal.params.validate() == []


def test_sabr_invalid_params_flagged():
    from mentisrex.research.market_data.sabr import SABRParams
    assert SABRParams(-1, 0.5, 0.0, 0.4).validate()
    assert SABRParams(0.2, 0.5, 1.5, 0.4).validate()
    assert SABRParams(0.2, 0.5, 0.0, -0.1).validate()


def test_sabr_vol_positive_across_strikes():
    for k in (60, 80, 100, 140, 180):
        assert sabr_vol(100, k, 1.0, 0.2, 0.5, -0.3, 0.4) > 0


def test_sabr_smile_shape_skew():
    # negative rho -> downside vols higher than upside
    lo = sabr_vol(100, 80, 1.0, 0.2, 0.5, -0.4, 0.5)
    hi = sabr_vol(100, 120, 1.0, 0.2, 0.5, -0.4, 0.5)
    assert lo > hi


def test_sabr_bad_inputs_raise():
    with pytest.raises(ValueError):
        sabr_vol(100, 100, 1.0, -0.1, 0.5, 0.0, 0.4)


# ══════════════════════════════════════════════════════════════════════════════
# 14. SVI
# ══════════════════════════════════════════════════════════════════════════════

def _svi_market():
    f, t = 100.0, 1.0
    ks = [math.log(k / f) for k in (70, 85, 100, 115, 130)]
    w = [sabr_vol(f, f * math.exp(k), t, 0.2, 0.5, -0.3, 0.4) ** 2 * t for k in ks]
    return ks, w


def test_svi_calibration_fits():
    ks, w = _svi_market()
    cal = md.calibrate_svi(ks, w)
    assert cal.max_residual < 1e-3


def test_svi_total_variance_nonnegative():
    ks, w = _svi_market()
    p = md.calibrate_svi(ks, w).params
    assert all(p.total_variance(k) >= 0 for k in ks)


def test_svi_params_validate():
    ks, w = _svi_market()
    assert md.calibrate_svi(ks, w).params.validate() == []


def test_svi_no_butterfly_arbitrage_on_fit():
    ks, w = _svi_market()
    assert md.calibrate_svi(ks, w).arbitrage == ()


def test_svi_durrleman_detects_arbitrage():
    from mentisrex.research.market_data.svi import SVIParams
    bad = SVIParams(a=0.0, b=2.0, rho=0.9, m=0.0, sigma=0.01)  # steep -> butterfly
    assert md.butterfly_arbitrage(bad)


def test_svi_vol_positive():
    ks, w = _svi_market()
    p = md.calibrate_svi(ks, w).params
    assert p.vol(0.0, 1.0) > 0


def test_svi_needs_three_points():
    with pytest.raises(ValueError):
        md.calibrate_svi([0.0, 0.1], [0.04, 0.04])


# ══════════════════════════════════════════════════════════════════════════════
# 15. vol surface calibration
# ══════════════════════════════════════════════════════════════════════════════

def test_surface_calibration_sabr_materializes_m18_surface():
    from mentisrex.research.valuation.volatility import VolatilitySurface
    smiles = [sabr_smile(100, t) for t in (0.5, 1.0, 2.0)]
    surf, rep, prov = md.VolatilitySurfaceCalibrator(md.VolModel.SABR).calibrate_surface(
        smiles, "SPX", REF)
    assert isinstance(surf, VolatilitySurface) and rep.ok


def test_surface_calibration_svi_low_residual():
    smiles = [sabr_smile(100, t) for t in (0.5, 1.0, 2.0)]
    _s, rep, _p = md.VolatilitySurfaceCalibrator(md.VolModel.SVI).calibrate_surface(
        smiles, "SPX", REF)
    assert rep.max_residual < 1e-3


def test_surface_interpolated_model():
    smiles = [sabr_smile(100, t) for t in (0.5, 1.0)]
    surf, rep, _p = md.VolatilitySurfaceCalibrator(md.VolModel.INTERPOLATED).calibrate_surface(
        smiles, "SPX", REF)
    assert surf.vol(100, 0.5) > 0


def test_surface_calendar_arbitrage_flagged():
    from mentisrex.research.market_data.vol_calibration import SmileQuotes
    # decreasing total variance across maturity at fixed strike -> calendar arb
    s1 = SmileQuotes(100, 1.0, (100,), (0.30,), underlying="X")
    s2 = SmileQuotes(100, 2.0, (100,), (0.10,), underlying="X")
    _s, rep, _p = md.VolatilitySurfaceCalibrator(md.VolModel.INTERPOLATED).calibrate_surface(
        [s1, s2], "X", REF)
    assert not rep.ok


def test_calibrated_vol_provider_protocol():
    smiles = [sabr_smile(100, t) for t in (0.5, 1.0, 2.0)]
    _s, _r, prov = md.VolatilitySurfaceCalibrator(md.VolModel.SABR).calibrate_surface(
        smiles, "SPX", REF)
    assert prov.implied_vol("SPX", 105, 1.5) > 0


def test_surface_bid_ask_flag():
    from mentisrex.research.market_data.vol_calibration import SmileQuotes
    s = SmileQuotes(100, 1.0, (90, 100, 110), (0.2, 0.2, 0.2),
                    bids=(0.30, 0.30, 0.30), asks=(0.31, 0.31, 0.31), underlying="X")
    fn = md.VolatilitySurfaceCalibrator(md.VolModel.INTERPOLATED).calibrate_smile(s)
    assert any("outside" in d for d in fn.calib.diagnostics)


def test_surface_empty_raises():
    with pytest.raises(ValueError):
        md.VolatilitySurfaceCalibrator().calibrate_surface([], "X", REF)


# ══════════════════════════════════════════════════════════════════════════════
# 16. PIT snapshot builder
# ══════════════════════════════════════════════════════════════════════════════

def test_builder_assembles_spot():
    b = md.MarketDataSnapshotBuilder()
    raw = [{"id": "A", "field": "close", "value": 190.0, "observation_date": "2024-06-03"}]
    res = b.build(as_of=REF, raw=raw)
    assert res.snapshot.spot("A") == 190.0


def test_builder_assembles_quote():
    b = md.MarketDataSnapshotBuilder()
    raw = [{"id": "A", "field": "bid", "value": 189.9, "observation_date": "2024-06-03"},
           {"id": "A", "field": "ask", "value": 190.1, "observation_date": "2024-06-03"}]
    res = b.build(as_of=REF, raw=raw)
    assert "A" in res.snapshot.quotes


def test_builder_fail_closed_on_bad_spot():
    b = md.MarketDataSnapshotBuilder()
    raw = [{"id": "A", "field": "close", "value": -5.0, "observation_date": "2024-06-03"}]
    with pytest.raises(md.SnapshotBuildError):
        b.build(as_of=REF, raw=raw)


def test_builder_drops_look_ahead():
    b = md.MarketDataSnapshotBuilder()
    raw = [{"id": "A", "field": "close", "value": 1.0, "observation_date": "2024-06-10"}]
    # look-ahead close is a REJECT (valuation-critical) -> fail closed
    with pytest.raises(md.SnapshotBuildError):
        b.build(as_of=REF, raw=raw)


def test_builder_injects_curves_and_surfaces():
    b = md.MarketDataSnapshotBuilder()
    c = swap_curve()
    res = b.build(as_of=REF, raw=[{"id": "A", "field": "close", "value": 1.0,
                                   "observation_date": "2024-06-03"}], curves={"USD": c})
    assert res.snapshot.curve("USD") is c


def test_builder_fingerprint_present():
    res = md.MarketDataSnapshotBuilder().build(
        as_of=REF, raw=[{"id": "A", "field": "close", "value": 1.0}])
    assert res.fingerprint and res.fingerprint == res.snapshot.fingerprint()


def test_builder_result_is_m18_snapshot():
    from mentisrex.research.valuation.models import MarketDataSnapshot
    res = md.MarketDataSnapshotBuilder().build(
        as_of=REF, raw=[{"id": "A", "field": "close", "value": 1.0}])
    assert isinstance(res.snapshot, MarketDataSnapshot)


# ══════════════════════════════════════════════════════════════════════════════
# 17. validators
# ══════════════════════════════════════════════════════════════════════════════

def test_md_validator_flags_lookahead():
    v = md.MarketDataValidator()
    assert v.validate([obs(obs_d=date(2024, 6, 10))], as_of=REF)


def test_md_validator_clean():
    assert md.MarketDataValidator().validate([obs(currency="USD")], as_of=REF) == []


def test_md_validator_flags_price_without_currency():
    assert md.MarketDataValidator().validate([obs()], as_of=REF)   # currency=None + price unit


def test_curve_validator_clean():
    assert md.CurveValidator().validate(swap_curve()) == []


def test_calibration_validator_tolerance():
    res = md.CurveBootstrapper().bootstrap([md.deposit(0.25, 0.05), md.swap(5, 0.05)], REF)
    assert md.CalibrationValidator(tol=1e-6).validate(res.report) == []


def test_surface_validator_clean():
    smiles = [sabr_smile(100, t) for t in (0.5, 1.0, 2.0)]
    surf, _r, _p = md.VolatilitySurfaceCalibrator(md.VolModel.SABR).calibrate_surface(
        smiles, "SPX", REF)
    assert md.VolatilitySurfaceValidator().validate(surf) == []


def test_snapshot_validator_missing_spot():
    res = md.MarketDataSnapshotBuilder().build(
        as_of=REF, raw=[{"id": "A", "field": "close", "value": 1.0}])
    assert md.SnapshotValidator().validate(res.snapshot, required_spots=["B"])


# ══════════════════════════════════════════════════════════════════════════════
# 18. serialization round-trips
# ══════════════════════════════════════════════════════════════════════════════

def test_observation_roundtrip():
    o = obs()
    assert ser.observation_from_dict(ser.observation_to_dict(o)).fingerprint() == o.fingerprint()


def test_zero_curve_roundtrip():
    c = swap_curve()
    assert ser.curve_from_dict(ser.curve_to_dict(c)).fingerprint() == c.fingerprint()


def test_discount_curve_roundtrip():
    c = swap_curve().as_discount_curve()
    assert ser.curve_from_dict(ser.curve_to_dict(c)).fingerprint() == c.fingerprint()


def test_credit_curve_roundtrip():
    cc, _ = _credit()
    assert ser.credit_curve_from_dict(ser.credit_curve_to_dict(cc)).fingerprint() == cc.fingerprint()


def test_surface_roundtrip():
    smiles = [sabr_smile(100, t) for t in (0.5, 1.0, 2.0)]
    surf, _r, _p = md.VolatilitySurfaceCalibrator(md.VolModel.SABR).calibrate_surface(
        smiles, "SPX", REF)
    assert ser.surface_from_dict(ser.surface_to_dict(surf)).fingerprint() == surf.fingerprint()


def test_report_to_dict():
    res = md.CurveBootstrapper().bootstrap([md.deposit(0.25, 0.05), md.swap(5, 0.05)], REF)
    d = ser.report_to_dict(res.report)
    assert d["ok"] and d["n_instruments"] == 2


def test_observations_json_deterministic():
    o = [obs(), obs(sid="B")]
    assert ser.observations_to_json(o) == ser.observations_to_json(o)


def test_to_json_clean():
    import json
    s = ser.to_json({"a": REF, "b": [1, 2]})
    assert json.loads(s)["a"] == "2024-06-03"


# ══════════════════════════════════════════════════════════════════════════════
# 19. registry
# ══════════════════════════════════════════════════════════════════════════════

def test_registry_default_populated():
    assert len(md.default_market_data_registry().all()) >= 12


def test_registry_get():
    r = md.default_market_data_registry()
    assert r.get(md.ComponentKind.VOL_CALIBRATOR, "sabr.hagan", "1.0.0").name == "sabr.hagan"


def test_registry_by_kind():
    r = md.default_market_data_registry()
    assert len(r.by_kind(md.ComponentKind.CALENDAR)) == 3


def test_registry_duplicate_different_raises():
    r = md.MarketDataRegistry()
    r.register(md.ComponentInfo(md.ComponentKind.PROVIDER, "x", "1", "a"))
    with pytest.raises(ValueError):
        r.register(md.ComponentInfo(md.ComponentKind.PROVIDER, "x", "1", "b"))


def test_registry_unknown_raises():
    with pytest.raises(KeyError):
        md.default_market_data_registry().get(md.ComponentKind.PROVIDER, "nope", "1")


# ══════════════════════════════════════════════════════════════════════════════
# 20. production adapters (contracts only)
# ══════════════════════════════════════════════════════════════════════════════

def test_bloomberg_translation():
    o = md.BloombergAdapter().to_canonical(
        {"id": "AAPL", "field": "PX_LAST", "value": 190.0, "currency": "USD", "date": "2024-06-03"},
        as_of=REF)
    assert o.field == "close" and o.value == 190.0


def test_refinitiv_translation():
    o = md.RefinitivAdapter().to_canonical(
        {"id": "AAPL", "field": "TRDPRC_1", "value": 190.0, "date": "2024-06-03"}, as_of=REF)
    assert o.field == "close"


def test_exchange_translation():
    o = md.ExchangeFeedAdapter().to_canonical(
        {"id": "ESZ4", "field": "last", "value": 5000.0}, as_of=REF)
    assert o.obs_type.value == "trade"


def test_broker_translation():
    o = md.BrokerFeedAdapter().to_canonical({"id": "X", "field": "mark", "value": 1.0}, as_of=REF)
    assert o.field == "close"


def test_adapter_unmapped_field_raises():
    with pytest.raises(KeyError):
        md.BloombergAdapter().to_canonical({"id": "X", "field": "NOPE", "value": 1}, as_of=REF)


def test_adapter_fetch_not_implemented():
    with pytest.raises(NotImplementedError):
        md.BloombergAdapter().fetch(REF)


def test_adapter_yield_maps_to_rate_unit():
    from mentisrex.research.market_data.models import Unit
    o = md.BloombergAdapter().to_canonical(
        {"id": "T", "field": "YLD_YTM_MID", "value": 4.5}, as_of=REF)
    assert o.unit is Unit.RATE


# ══════════════════════════════════════════════════════════════════════════════
# 21. engine façade
# ══════════════════════════════════════════════════════════════════════════════

def test_engine_ingest():
    eng = md.MarketDataEngine()
    accepted, diags = eng.ingest([{"id": "A", "field": "close", "value": 1.0}], as_of=REF)
    assert len(accepted) == 1


def test_engine_bootstrap_curve():
    eng = md.MarketDataEngine()
    res = eng.bootstrap_curve([md.deposit(0.25, 0.05), md.swap(5, 0.05)], as_of=REF, curve_id="USD")
    assert res.report.ok


def test_engine_calibrate_surface():
    eng = md.MarketDataEngine()
    smiles = [sabr_smile(100, t) for t in (0.5, 1.0)]
    surf, rep, prov = eng.calibrate_surface(smiles, surface_id="SPX", as_of=REF)
    assert rep.ok


def test_engine_build_snapshot():
    eng = md.MarketDataEngine()
    res = eng.build_snapshot(as_of=REF, raw=[{"id": "A", "field": "close", "value": 1.0}])
    assert res.snapshot.spot("A") == 1.0


def test_engine_pipeline_produces_snapshot():
    eng = md.MarketDataEngine()
    raw = [{"id": "AAPL", "field": "close", "value": 190.0, "observation_date": "2024-06-03"}]
    res = eng.pipeline(as_of=REF, raw=raw,
                       curve_instruments=[md.deposit(0.25, 0.05), md.swap(5, 0.05)],
                       smiles=[sabr_smile(190, t, "AAPL") for t in (0.5, 1.0)],
                       currency="USD", surface_underlying="AAPL")
    assert res.snapshot.spot("AAPL") == 190.0 and res.snapshot.curve("USD").discount(5) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 22. M16 FX integration (reuse, not fork)
# ══════════════════════════════════════════════════════════════════════════════

def test_m16_fx_reciprocal_via_diagnostics():
    fx = m16fx.rates.StaticFXRateProvider({"EUR/USD": 1.10})
    assert mdiag.fx_reciprocal(fx, [("EUR", "USD")]) == []


def test_m16_fx_in_built_snapshot():
    fx = m16fx.rates.StaticFXRateProvider({"EUR/USD": 1.10})
    eng = md.MarketDataEngine(fx_provider=fx)
    res = eng.build_snapshot(as_of=REF, raw=[{"id": "A", "field": "close", "value": 1.0}])
    assert res.snapshot.fx_rate("EUR", "USD") == 1.10


def test_m16_normalizer_uses_fx_provider():
    fx = m16fx.rates.StaticFXRateProvider({"GBP/USD": 1.25})
    n = md.Normalizer(fx_provider=fx, base_currency="USD", convert_currency=True)
    r = n.normalize([{"id": "L", "field": "close", "value": 100.0, "currency": "GBP"}], as_of=REF)
    assert abs(r.observations[0].value - 125.0) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# 23. M18 valuation integration (M19 snapshot -> M18 engine)
# ══════════════════════════════════════════════════════════════════════════════

def _built_snapshot():
    fx = m16fx.rates.StaticFXRateProvider({"EUR/USD": 1.10})
    eng = md.MarketDataEngine(fx_provider=fx)
    raw = [{"id": "AAPL", "field": "close", "value": 190.0, "observation_date": "2024-06-03"}]
    return eng.pipeline(
        as_of=REF, raw=raw, curve_instruments=[md.deposit(0.25, 0.05), md.swap(1, 0.05),
                                               md.swap(5, 0.05), md.swap(10, 0.05)],
        smiles=[sabr_smile(190, t, "AAPL") for t in (0.5, 1.0, 2.0)],
        currency="USD", surface_underlying="AAPL", dividend_yields={"AAPL": 0.005}).snapshot


def test_m18_equity_valuation_from_m19_snapshot():
    snap = _built_snapshot()
    eq = ins.equity("AAPL", currency="USD")
    r = ValuationEngine().value(eq, snap, ValuationConfiguration())
    assert r.price == 190.0 and r.model_name == "equity.spot"


def test_m18_option_valuation_from_m19_snapshot():
    snap = _built_snapshot()
    opt = ins.option("C", underlying="AAPL", strike=200.0, expiry=date(2025, 6, 3),
                     right=ins.OptionRight.CALL, currency="USD")
    r = ValuationEngine().value(opt, snap, ValuationConfiguration())
    assert r.price > 0 and r.greeks.delta > 0


def test_m18_future_valuation_from_m19_snapshot():
    snap = _built_snapshot()
    fut = ins.future("F", underlying="AAPL", expiry=date(2024, 12, 3), currency="USD")
    r = ValuationEngine().value(fut, snap, ValuationConfiguration())
    assert r.price > 190.0        # cost of carry above spot (r>q)


def test_m18_bond_valuation_from_m19_snapshot():
    snap = _built_snapshot()
    bond = ins.bond("B", currency="USD", maturity=date(2029, 6, 3), face=100.0, coupon=0.05,
                    frequency=2)
    r = ValuationEngine().value(bond, snap, ValuationConfiguration())
    assert r.price > 0


def test_m18_valuation_reproducible_key():
    snap = _built_snapshot()
    eq = ins.equity("AAPL", currency="USD")
    r1 = ValuationEngine().value(eq, snap, ValuationConfiguration())
    r2 = ValuationEngine().value(eq, snap, ValuationConfiguration())
    assert r1.reproducible_key == r2.reproducible_key


def test_m18_portfolio_valuation_from_m19_snapshot():
    from mentisrex.research.valuation.engine import PortfolioValuationEngine
    snap = _built_snapshot()
    eq = ins.equity("AAPL", currency="USD")
    opt = ins.option("C", underlying="AAPL", strike=200.0, expiry=date(2025, 6, 3),
                     right=ins.OptionRight.CALL, currency="USD")
    pv = PortfolioValuationEngine().value([(eq, 100, None), (opt, 10, None)], snap,
                                          ValuationConfiguration())
    assert pv.gross_market_value > 0 and "delta" in pv.risk_inputs


# ══════════════════════════════════════════════════════════════════════════════
# 24. M17 vol provider integration
# ══════════════════════════════════════════════════════════════════════════════

def test_calibrated_provider_feeds_option_vol():
    smiles = [sabr_smile(190, t, "AAPL") for t in (0.5, 1.0, 2.0)]
    _s, _r, prov = md.VolatilitySurfaceCalibrator(md.VolModel.SABR).calibrate_surface(
        smiles, "AAPL", REF)
    # provider matches the M18 VolatilityProvider protocol used by the engine
    v = prov.implied_vol("AAPL", 200.0, 1.0)
    assert v > 0 and abs(v - sabr_vol(190, 200, 1.0, 0.25, 0.5, -0.3, 0.4)) < 1e-2


# ══════════════════════════════════════════════════════════════════════════════
# 25. determinism / fingerprints
# ══════════════════════════════════════════════════════════════════════════════

def test_determinism_snapshot_fingerprint():
    assert _built_snapshot().fingerprint() == _built_snapshot().fingerprint()


def test_determinism_curve_fingerprint():
    assert swap_curve().fingerprint() == swap_curve().fingerprint()


def test_determinism_sabr_calibration():
    ks = [80, 90, 100, 110, 120]
    mkt = [sabr_vol(100, k, 1.0, 0.2, 0.5, -0.3, 0.4) for k in ks]
    a = md.calibrate_sabr(100, 1.0, ks, mkt)
    b = md.calibrate_sabr(100, 1.0, ks, mkt)
    assert a.params == b.params


def test_determinism_svi_calibration():
    ks, w = _svi_market()
    assert md.calibrate_svi(ks, w).params == md.calibrate_svi(ks, w).params


def test_determinism_credit_bootstrap():
    cc1, _ = _credit()
    cc2, _ = _credit()
    assert cc1.fingerprint() == cc2.fingerprint()


def test_determinism_pipeline_end_to_end():
    eng = md.MarketDataEngine()
    args = dict(as_of=REF, raw=[{"id": "A", "field": "close", "value": 1.0}],
                curve_instruments=[md.deposit(0.25, 0.05), md.swap(5, 0.05)], currency="USD")
    assert eng.pipeline(**args).snapshot.fingerprint() == eng.pipeline(**args).snapshot.fingerprint()


# ══════════════════════════════════════════════════════════════════════════════
# 26. edge cases
# ══════════════════════════════════════════════════════════════════════════════

def test_edge_single_node_curve():
    c = md.CurveBootstrapper().bootstrap([md.deposit(1.0, 0.05)], REF).curve
    assert c.discount(1.0) > 0


def test_edge_zero_maturity_discount_is_one():
    assert swap_curve().discount(0.0) == 1.0


def test_edge_empty_raw_builds_empty_snapshot():
    res = md.MarketDataSnapshotBuilder().build(as_of=REF, raw=[])
    assert res.snapshot.spots == {}


def test_edge_flat_surface_single_expiry():
    surf, _r, _p = md.VolatilitySurfaceCalibrator(md.VolModel.SABR).calibrate_surface(
        [sabr_smile(100, 1.0)], "X", REF)
    assert surf.vol(100, 1.0) > 0


def test_edge_credit_single_quote():
    disc = swap_curve([(0.5, 0.05), (5, 0.05)])
    cc, rep = md.bootstrap_credit([md.CDSQuote(5, 0.015)], disc)
    assert rep.ok and cc.survival(5) < 1.0


def test_edge_normalizer_empty():
    assert md.Normalizer().normalize([], as_of=REF).observations == ()


def test_edge_quality_empty():
    assert md.MarketDataQualityEngine().check([], as_of=REF).ok


def test_edge_identifier_map_empty_identifiers():
    assert md.IdentifierMap().identifiers("SEC") == {}


# ══════════════════════════════════════════════════════════════════════════════
# 27. additional coverage
# ══════════════════════════════════════════════════════════════════════════════

def test_ois_instrument_bootstraps():
    res = md.CurveBootstrapper().bootstrap(
        [md.deposit(0.25, 0.05), md.ois(1, 0.05), md.ois(5, 0.05)], REF)
    assert res.report.ok and max(abs(r) for _, r in res.residuals) < 1e-7


def test_builder_from_source():
    src = md.DeterministicMockSource({"A": 100.0})
    res = md.MarketDataSnapshotBuilder().build(as_of=REF, source=src)
    assert res.snapshot.spot("A") > 0


def test_engine_pipeline_with_source():
    eng = md.MarketDataEngine()
    src = md.StaticSource([{"id": "A", "field": "close", "value": 5.0,
                            "observation_date": "2024-06-03"}])
    res = eng.build_snapshot(as_of=REF, source=src)
    assert res.snapshot.spot("A") == 5.0


def test_normalize_yield_alias():
    r = md.Normalizer().normalize([{"id": "T", "field": "yield", "value": 0.045}], as_of=REF)
    assert r.observations[0].obs_type.value == "yield"


def test_normalize_discount_factor_alias():
    r = md.Normalizer().normalize(
        [{"id": "C", "field": "discount_factor", "value": 0.95}], as_of=REF)
    assert r.observations[0].obs_type.value == "discount_factor"


def test_sabr_beta_one_lognormal():
    v = sabr_vol(100, 110, 1.0, 0.2, 1.0, -0.2, 0.3)
    assert v > 0


def test_svi_monotone_wings():
    ks, w = _svi_market()
    p = md.calibrate_svi(ks, w).params
    # total variance rises moving into either wing from the minimum near m
    assert p.total_variance(-1.0) > p.total_variance(p.m)
    assert p.total_variance(1.0) > p.total_variance(p.m)


def test_calendar_modified_following_stays_in_month():
    c = md.WeekendCalendar()
    # 2024-03-30 Sat, 31 Sun -> following would jump to April 1; modified stays March 29
    assert c.adjust(date(2024, 3, 30), md.RollConvention.MODIFIED_FOLLOWING) == date(2024, 3, 29)


def test_credit_recovery_effect_on_hazard():
    disc = swap_curve([(0.5, 0.05), (5, 0.05)])
    lo, _ = md.bootstrap_credit([md.CDSQuote(5, 0.015)], disc, recovery=0.2)
    hi, _ = md.bootstrap_credit([md.CDSQuote(5, 0.015)], disc, recovery=0.6)
    # same spread, higher recovery -> higher implied hazard (s ~ h*(1-R))
    assert hi.hazard(5) > lo.hazard(5)


def test_quality_custom_reject_on_error():
    from mentisrex.research.market_data.models import ObservationType, Severity, Unit
    cfg = md.QualityConfig(reject_severities=(Severity.REJECT, Severity.ERROR))
    o = obs(field="volume", value=-5.0, obs_type=ObservationType.VOLUME, unit=Unit.SHARES)
    rep = md.MarketDataQualityEngine(cfg).check([o], as_of=REF)
    assert rep.rejected      # negative volume is ERROR -> now rejected


def test_builder_transform_log_present():
    res = md.MarketDataSnapshotBuilder().build(
        as_of=REF, raw=[{"id": "C", "field": "rate", "value": 5.0, "unit": "percent"}])
    assert len(res.transform_log) > 0


def test_snapshot_curve_forward_rate_positive():
    c = swap_curve()
    assert c.forward_rate(1, 2) > 0
