"""Production market-data adapter contracts (AIDP M19).

The M18 deferred item: a production feed. These adapters define the **exact translation
contract** a real vendor connector must satisfy — the field-name map and the raw→canonical
transform — without shipping any live functionality. `to_canonical` is fully implemented and
testable (pure schema translation); `fetch` raises `NotImplementedError` with the specific
unblock, because this platform is offline by mandate: no credentials, no network, no false claim
of a live feed.

Covered: Bloomberg, Refinitiv, a generic exchange feed and a generic broker feed. A production
implementation subclasses one, wires `fetch` to the real endpoint, and inherits the tested
translation.
"""

from __future__ import annotations

from datetime import date

from mentisrex.research.market_data.models import (
    CanonicalObservation,
    ObservationType,
    Unit,
)
from mentisrex.research.market_data.sources import MarketDataSource


class VendorAdapter(MarketDataSource):
    """Base production adapter: a vendor field map + a pure raw→canonical translation. Subclasses
    only differ by `FIELD_MAP`/`source`; the live `fetch` is left unimplemented on purpose."""
    source = "vendor"
    FIELD_MAP: dict = {}                    # vendor field name -> (canonical field, ObservationType)

    def to_canonical(self, raw: dict, *, as_of: date) -> CanonicalObservation:
        """Translate one vendor record into a canonical observation (no network — pure mapping)."""
        vendor_field = raw.get("field") or raw.get("fld")
        canon = self.FIELD_MAP.get(vendor_field)
        if canon is None:
            raise KeyError(f"{self.source}: unmapped vendor field {vendor_field!r}")
        field_name, obs_type = canon
        unit = Unit.RATE if obs_type in (ObservationType.INTEREST_RATE, ObservationType.YIELD) else Unit.PRICE
        obs_d = _d(raw.get("date") or raw.get("asof") or as_of)
        return CanonicalObservation(
            security_id=str(raw.get("id") or raw.get("ticker") or raw.get("security")),
            obs_type=obs_type, field=field_name, value=float(raw["value"]),
            observation_date=obs_d, effective_date=_d(raw.get("effective") or obs_d),
            source=self.source, currency=raw.get("currency"), unit=unit,
            revision=int(raw.get("revision", 0)))

    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[dict]:
        raise NotImplementedError(
            f"{self.source}: no live feed in this offline platform. Unblock: implement fetch() "
            f"against the real endpoint (auth + request) returning raw records; to_canonical() "
            f"already maps them to PIT-tagged canonical observations.")


class BloombergAdapter(VendorAdapter):
    source = "bloomberg"
    FIELD_MAP = {
        "PX_LAST": ("close", ObservationType.CLOSE),
        "PX_BID": ("bid", ObservationType.QUOTE),
        "PX_ASK": ("ask", ObservationType.QUOTE),
        "PX_VOLUME": ("volume", ObservationType.VOLUME),
        "OPEN_INT": ("open_interest", ObservationType.OPEN_INTEREST),
        "YLD_YTM_MID": ("yield", ObservationType.YIELD),
        "IVOL_MID": ("implied_vol", ObservationType.VOLATILITY),
    }


class RefinitivAdapter(VendorAdapter):
    source = "refinitiv"
    FIELD_MAP = {
        "TRDPRC_1": ("close", ObservationType.CLOSE),
        "BID": ("bid", ObservationType.QUOTE),
        "ASK": ("ask", ObservationType.QUOTE),
        "ACVOL_UNS": ("volume", ObservationType.VOLUME),
        "YIELD": ("yield", ObservationType.YIELD),
    }


class ExchangeFeedAdapter(VendorAdapter):
    source = "exchange"
    FIELD_MAP = {
        "last": ("close", ObservationType.TRADE),
        "bid": ("bid", ObservationType.QUOTE),
        "ask": ("ask", ObservationType.QUOTE),
        "volume": ("volume", ObservationType.VOLUME),
        "open_interest": ("open_interest", ObservationType.OPEN_INTEREST),
    }


class BrokerFeedAdapter(VendorAdapter):
    source = "broker"
    FIELD_MAP = {
        "mark": ("close", ObservationType.CLOSE),
        "bid": ("bid", ObservationType.QUOTE),
        "ask": ("ask", ObservationType.QUOTE),
    }


def _d(v):
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        return date.fromisoformat(v[:10])
    return v
