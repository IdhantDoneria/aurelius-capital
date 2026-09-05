"""FRED (Federal Reserve Economic Data) provider adapter (AIDP M21).

FRED data is public domain from the Federal Reserve Bank of St. Louis. An API key is optional
(higher rate limits). Data is available at https://fred.stlouisfed.org/docs/api/fred/.

PIT safety — the critical bitemporal distinction:
    observation_date = realtime_start   (when FRED made this value publicly knowable)
    effective_date   = date             (the economic period the value is for)

Example: GDP Q1 2025 (period end 2025-03-31) is released on ~2025-04-30.
    effective_date:   2025-01-01  (start of the economic period, or whatever FRED reports)
    observation_date: 2025-04-30  (when the value was first published)

FRED also provides vintage data (realtime history) — every revision to a series gets its own
realtime_start, so the full bitemporal picture is reconstructable. This adapter preserves that.

fetch() raises NotImplementedError. Use convert(observations, series_id, as_of) offline.
"""

from __future__ import annotations

from datetime import date, datetime

from mentisrex.research.market_data_ops.adapters import SourceAdapter, SourceMetadata
from mentisrex.research.market_data_ops.messages import (
    MessageType,
    SourceCapability,
    SourceMessage,
)

# FRED series → canonical field name
_SERIES_MAP: dict[str, str] = {
    "GDP": "gdp",
    "GDPC1": "real_gdp",
    "CPIAUCSL": "cpi",
    "CPILFESL": "core_cpi",
    "UNRATE": "unemployment_rate",
    "FEDFUNDS": "fed_funds_rate",
    "DGS10": "treasury_10y",
    "DGS2": "treasury_2y",
    "DGS30": "treasury_30y",
    "DFF": "effective_fed_funds",
    "M2SL": "m2_money_supply",
    "M1SL": "m1_money_supply",
    "BAMLH0A0HYM2": "hy_spread",
    "BAMLC0A0CM": "ig_spread",
    "VIXCLS": "vix",
    "SP500": "sp500",
    "DEXUSEU": "fx_eur_usd",
    "DEXJPUS": "fx_jpy_usd",
    "DEXGBUS": "fx_gbp_usd",
    "INDPRO": "industrial_production",
    "PAYEMS": "nonfarm_payrolls",
    "HOUST": "housing_starts",
    "UMCSENT": "consumer_sentiment",
    "PCE": "personal_consumption",
    "PCEPI": "pce_deflator",
}


class FREDSourceAdapter(SourceAdapter):
    """Production contract wrapping FRED vintage-aware observation data.

    FRED API returns observations shaped as:
        {
          "observations": [
            {
              "realtime_start": "2024-04-30",  ← when FRED published this value
              "realtime_end":   "2024-07-30",  ← when this vintage was superseded
              "date":           "2024-01-01",  ← economic period
              "value":          "27357.0"
            }
          ]
        }

    Without vintage data, the simpler format is:
        [{"date": "2024-01-01", "value": "27357.0"}]
    In that case, knowledge_date is assumed equal to effective_date (look-ahead risk — use
    vintage endpoints for PIT-safe research).
    """

    def __init__(self, *, name: str = "fred") -> None:
        super().__init__(
            SourceMetadata(
                name,
                frozenset(
                    {
                        SourceCapability.HISTORICAL,
                        SourceCapability.RATES,
                    }
                ),
                schema_version="1.0",
                description="FRED macro data — bitemporal vintage-aware",
                vendor="fred",
            )
        )
        self._seq = 0

    def fetch(self, as_of: date, *, security_ids=None, fields=None) -> list[SourceMessage]:
        raise NotImplementedError(
            "fred.fetch: call the FRED vintage API at "
            "https://fred.stlouisfed.org/docs/api/fred/series_observations.html "
            "with realtime_start/realtime_end params, then call "
            "convert(response['observations'], series_id, as_of)."
        )

    def convert(
        self,
        observations: list[dict],
        series_id: str,
        as_of: date,
        *,
        unit: str | None = None,
        currency: str | None = None,
    ) -> list[SourceMessage]:
        """Convert FRED observation list to SourceMessage (offline, testable).

        observations: list of FRED observation dicts (may include realtime_start for PIT).
        series_id: FRED series key, e.g. "GDP", "UNRATE".
        """
        if self._state.value == "disconnected":
            self.connect()
        field = _SERIES_MAP.get(series_id.upper(), series_id.lower())
        msgs = []
        # sort by (realtime_start, date) for deterministic revision numbering
        sorted_obs = sorted(
            observations,
            key=lambda o: (
                str(o.get("realtime_start") or o.get("date") or ""),
                str(o.get("date") or ""),
            ),
        )
        revision_counter: dict[str, int] = {}
        for obs in sorted_obs:
            effective = _parse_date(obs.get("date"))
            knowledge = _parse_date(obs.get("realtime_start")) or effective
            if effective is None or knowledge is None:
                continue
            # PIT gate: reject observations not yet knowable as_of
            if knowledge > as_of:
                continue
            raw_val = obs.get("value", ".")
            if raw_val in (".", "", None):
                continue  # FRED uses "." for missing values
            try:
                val = float(raw_val)
            except (TypeError, ValueError):
                continue

            eff_key = effective.isoformat()
            rev = revision_counter.get(eff_key, 0)
            revision_counter[eff_key] = rev + 1

            payload: dict = {
                "id": series_id,
                "field": field,
                "value": val,
                "observation_date": knowledge.isoformat(),
                "effective_date": effective.isoformat(),
                "source": self.metadata.name,
                "series_id": series_id,
                "revision": rev,
            }
            if obs.get("realtime_end"):
                payload["realtime_end"] = str(obs["realtime_end"])
            if unit:
                payload["unit"] = unit
            if currency:
                payload["currency"] = currency

            self._seq += 1
            msgs.append(
                SourceMessage(
                    source=self.metadata.name,
                    payload=payload,
                    msg_type=MessageType.REVISION if rev > 0 else MessageType.OBSERVATION,
                    vendor_id=f"{series_id}:{effective.isoformat()}",
                    sequence=self._seq,
                    observation_date=knowledge,
                    effective_date=effective,
                    schema_version=self.metadata.schema_version,
                )
            )
        return self._record(msgs)


def _parse_date(v) -> date | None:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        try:
            return date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None
