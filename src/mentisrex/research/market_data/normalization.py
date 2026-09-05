"""Normalization pipeline (AIDP M19).

Turns messy raw vendor records into canonical observations through an auditable sequence:

    schema validation → identifier normalization → unit normalization → currency normalization
    → timestamp normalization → duplicate/revision resolution → (quality/PIT handled downstream)

Every transformation appends to a transform log and, on a problem, emits a structured
`QualityDiagnostic` rather than silently coercing. The step that *decides* to keep or drop a
datum (quality, PIT) is the quality engine and the snapshot builder — normalization's job is to
produce a well-typed, de-duplicated canonical stream and record what it did.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from mentisrex.research.market_data.identifiers import IdentifierMap, IdType
from mentisrex.research.market_data.models import (
    CanonicalObservation,
    ObservationType,
    QualityDiagnostic,
    Severity,
    Unit,
)

# field-name aliases → canonical field + observation type
_DEFAULT_ALIASES = {
    "close": ("close", ObservationType.CLOSE),
    "c": ("close", ObservationType.CLOSE),
    "adj_close": ("close", ObservationType.ADJ_CLOSE),
    "adjusted_close": ("close", ObservationType.ADJ_CLOSE),
    "last": ("close", ObservationType.TRADE),
    "price": ("close", ObservationType.TRADE),
    "bid": ("bid", ObservationType.QUOTE),
    "ask": ("ask", ObservationType.QUOTE),
    "volume": ("volume", ObservationType.VOLUME),
    "vol": ("volume", ObservationType.VOLUME),
    "open_interest": ("open_interest", ObservationType.OPEN_INTEREST),
    "rate": ("zero_rate", ObservationType.INTEREST_RATE),
    "yield": ("yield", ObservationType.YIELD),
    "discount_factor": ("discount_factor", ObservationType.DISCOUNT_FACTOR),
    "forward": ("forward", ObservationType.FORWARD),
    "implied_vol": ("implied_vol", ObservationType.VOLATILITY),
    "fx": ("fx_rate", ObservationType.FX_RATE),
    "fx_rate": ("fx_rate", ObservationType.FX_RATE),
}

_UNIT_ALIASES = {
    "price": Unit.PRICE,
    "rate": Unit.RATE,
    "percent": Unit.PERCENT,
    "pct": Unit.PERCENT,
    "bp": Unit.BASIS_POINT,
    "basis_point": Unit.BASIS_POINT,
    "bps": Unit.BASIS_POINT,
    "factor": Unit.FACTOR,
    "vol": Unit.VOL,
    "shares": Unit.SHARES,
    "contracts": Unit.CONTRACTS,
    "none": Unit.NONE,
}


@dataclass(frozen=True)
class NormalizationResult:
    observations: tuple = ()
    diagnostics: tuple = ()
    transform_log: tuple = ()

    @property
    def ok(self) -> bool:
        return not any(d.severity in (Severity.ERROR, Severity.REJECT) for d in self.diagnostics)


class Normalizer:
    """Convention-injected. `id_map` resolves external ids PIT-aware; `base_currency` and an
    `fx_provider` (M16) enable optional currency conversion; conventions are never assumed."""

    def __init__(
        self,
        *,
        id_map: IdentifierMap | None = None,
        fx_provider=None,
        base_currency: str = "USD",
        convert_currency: bool = False,
        field_aliases: dict | None = None,
        unit_aliases: dict | None = None,
        default_unit: Unit = Unit.PRICE,
    ) -> None:
        self.id_map = id_map
        self.fx_provider = fx_provider
        self.base_currency = base_currency
        self.convert_currency = convert_currency
        self.field_aliases = {**_DEFAULT_ALIASES, **(field_aliases or {})}
        self.unit_aliases = {**_UNIT_ALIASES, **(unit_aliases or {})}
        self.default_unit = default_unit

    def normalize(self, raw: list[dict], *, as_of: date) -> NormalizationResult:
        canon: list[CanonicalObservation] = []
        diags: list[QualityDiagnostic] = []
        log: list[str] = []
        for i, rec in enumerate(raw):
            obs = self._one(rec, as_of, i, diags, log)
            if obs is not None:
                canon.append(obs)
        deduped = self._resolve_revisions(canon, log)
        return NormalizationResult(tuple(deduped), tuple(diags), tuple(log))

    # ── per-record transform ──────────────────────────────────────────────────
    def _one(self, rec: dict, as_of, i, diags, log) -> CanonicalObservation | None:
        raw_id = rec.get("id", rec.get("security_id"))
        raw_field = rec.get("field") or rec.get("type")
        if raw_id is None or raw_field is None:
            diags.append(
                QualityDiagnostic(
                    "schema",
                    Severity.REJECT,
                    f"record {i} missing id/field",
                    str(raw_id),
                    str(raw_field),
                )
            )
            return None

        # identifier normalization
        sec_id = self._resolve_id(rec, str(raw_id), as_of, diags, log)

        # field + observation type
        alias = self.field_aliases.get(str(raw_field).lower())
        if alias is None:
            field_name, obs_type = str(raw_field), _guess_type(rec)
        else:
            field_name, obs_type = alias

        # value
        value = rec.get("value")
        if value is None and field_name in rec:
            value = rec.get(field_name)
        try:
            value = None if value is None else float(value)
        except (TypeError, ValueError):
            diags.append(
                QualityDiagnostic(
                    "bad_value", Severity.REJECT, f"non-numeric value {value!r}", sec_id, field_name
                )
            )
            return None

        # unit normalization → decimals for rates
        unit_raw = str(rec.get("unit", "")).lower()
        unit = self.unit_aliases.get(unit_raw, self.default_unit)
        value, unit = self._normalize_unit(value, unit, log, sec_id)

        # timestamp + dates
        obs_date = _to_date(
            rec.get("observation_date") or rec.get("date") or rec.get("effective_date")
        )
        eff_date = _to_date(rec.get("effective_date")) or obs_date
        if obs_date is None:
            obs_date = as_of
            log.append(f"{sec_id}.{field_name}: no observation_date, defaulted to as_of {as_of}")
        ts = _to_datetime(rec.get("timestamp"))
        if ts is not None and ts.date() != obs_date:
            log.append(f"{sec_id}.{field_name}: timestamp {ts} vs obs_date {obs_date} (kept both)")

        currency = rec.get("currency")
        if currency is not None:
            currency = str(currency).upper()
        value, currency = self._normalize_currency(value, currency, unit, obs_date, log, sec_id)

        meta = {
            k: rec[k]
            for k in (
                "bid",
                "ask",
                "volume",
                "open",
                "high",
                "low",
                "strike",
                "maturity",
                "underlying",
            )
            if k in rec
        }
        return CanonicalObservation(
            security_id=sec_id,
            obs_type=obs_type,
            field=field_name,
            value=value,
            observation_date=obs_date,
            effective_date=eff_date,
            source=str(rec.get("source", "unknown")),
            timestamp=ts,
            currency=currency,
            unit=unit,
            revision=int(rec.get("revision", 0)),
            meta=meta,
        )

    def _resolve_id(self, rec, raw_id, as_of, diags, log) -> str:
        id_type = rec.get("id_type")
        if self.id_map is not None and id_type is not None:
            try:
                sid = self.id_map.resolve(IdType(str(id_type)), raw_id, as_of=as_of)
                if sid != raw_id:
                    log.append(f"id {id_type}:{raw_id} -> security {sid}")
                return sid
            except (KeyError, ValueError) as e:
                diags.append(
                    QualityDiagnostic("id_unresolved", Severity.WARNING, str(e), raw_id, None)
                )
        return raw_id

    def _normalize_unit(self, value, unit, log, sec_id):
        if value is None:
            return value, unit
        if unit is Unit.PERCENT:
            log.append(f"{sec_id}: percent {value} -> rate {value / 100.0}")
            return value / 100.0, Unit.RATE
        if unit is Unit.BASIS_POINT:
            log.append(f"{sec_id}: {value}bp -> rate {value / 1e4}")
            return value / 1e4, Unit.RATE
        return value, unit

    def _normalize_currency(self, value, currency, unit, obs_date, log, sec_id):
        if (
            not self.convert_currency
            or value is None
            or currency is None
            or unit not in (Unit.PRICE,)
            or currency == self.base_currency
            or self.fx_provider is None
        ):
            return value, currency
        rate = self.fx_provider.rate(currency, self.base_currency, as_of=obs_date)
        log.append(f"{sec_id}: {value} {currency} -> {value * rate} {self.base_currency} @ {rate}")
        return value * rate, self.base_currency

    def _resolve_revisions(self, obs, log) -> list[CanonicalObservation]:
        """Collapse duplicates on (security, obs_type, field, effective_date): keep the highest
        revision; ties broken by latest observation_date. Duplicates are logged, not dropped
        silently."""
        best: dict[tuple, CanonicalObservation] = {}
        for o in obs:
            k = o.key
            cur = best.get(k)
            if cur is None:
                best[k] = o
            elif (o.revision, o.observation_date) > (cur.revision, cur.observation_date):
                log.append(f"revision: {k} r{cur.revision}->r{o.revision} (superseded)")
                best[k] = o
            else:
                log.append(f"duplicate: {k} dropped r{o.revision} (kept r{cur.revision})")
        return sorted(best.values(), key=lambda o: (o.security_id, o.field, o.effective_date))


# ── helpers ───────────────────────────────────────────────────────────────────


def _guess_type(rec: dict) -> ObservationType:
    t = str(rec.get("type", "")).lower()
    for ot in ObservationType:
        if ot.value == t:
            return ot
    return ObservationType.REFERENCE


def _to_date(v):
    if v is None or (isinstance(v, date) and not isinstance(v, datetime)):
        return v.date() if isinstance(v, datetime) else v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        return date.fromisoformat(v[:10])
    return None


def _to_datetime(v):
    if v is None or isinstance(v, datetime):
        return v
    if isinstance(v, str):
        return datetime.fromisoformat(v)
    return None
