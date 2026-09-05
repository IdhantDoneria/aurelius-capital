"""Point-in-time snapshot builder (AIDP M19).

M18 validates a snapshot's PIT safety; M19 *builds* the snapshot correctly in the first place.
`MarketDataSnapshotBuilder` takes a valuation date, raw records (or a source), plus already-
calibrated curves / vol surfaces / dividends / forwards / an M16 FX provider, and assembles an
immutable M18 `MarketDataSnapshot`:

    raw → normalize → quality → PIT enforcement → assemble → M18 validate_pit → snapshot

It is fail-closed on valuation-critical data (a rejected spot raises), warning-only on the rest,
and every build carries provenance + a fingerprint. Look-ahead is structurally impossible: any
observation dated after the valuation date is dropped before assembly and re-checked by M18.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from mentisrex.research.market_data.normalization import NormalizationResult, Normalizer
from mentisrex.research.market_data.quality import MarketDataQualityEngine, QualityConfig
from mentisrex.research.valuation.models import MarketDataSnapshot, MarketQuote, Provenance
from mentisrex.research.valuation.snapshot import validate_pit


@dataclass(frozen=True)
class PITPolicy:
    max_staleness_days: int | None = None
    reject_look_ahead: bool = True
    fail_closed: bool = True  # raise if a valuation-critical datum is rejected


@dataclass(frozen=True)
class BuildResult:
    snapshot: MarketDataSnapshot
    diagnostics: tuple = ()
    observations: tuple = ()
    transform_log: tuple = ()
    fingerprint: str = ""


class SnapshotBuildError(ValueError):
    pass


class MarketDataSnapshotBuilder:
    def __init__(
        self,
        *,
        normalizer: Normalizer | None = None,
        quality: MarketDataQualityEngine | None = None,
        source: str = "m19",
    ) -> None:
        self.normalizer = normalizer or Normalizer()
        self.quality = quality or MarketDataQualityEngine()
        self.source = source

    def build(
        self,
        *,
        as_of: date,
        raw: list[dict] | None = None,
        source=None,
        security_ids=None,
        fields=None,
        curves=None,
        discount_curves=None,
        vol_surfaces=None,
        dividend_yields=None,
        forwards=None,
        fx_provider=None,
        corporate_actions=None,
        policy: PITPolicy | None = None,
    ) -> BuildResult:
        policy = policy or PITPolicy(max_staleness_days=self.quality.config.max_staleness_days)
        if raw is None:
            if source is None:
                raw = []
            else:
                raw = source.fetch(as_of, security_ids=security_ids, fields=fields)

        norm: NormalizationResult = self.normalizer.normalize(raw, as_of=as_of)
        qcfg = QualityConfig(
            max_staleness_days=policy.max_staleness_days,
            max_spread_frac=self.quality.config.max_spread_frac,
            max_jump_frac=self.quality.config.max_jump_frac,
        )
        qrep = MarketDataQualityEngine(qcfg).check(norm.observations, as_of=as_of)
        diags = list(norm.diagnostics) + list(qrep.diagnostics)

        # fail-closed on rejected valuation-critical (spot) data
        if policy.fail_closed:
            for obs in qrep.rejected:
                if obs.field in ("close", "last") or obs.obs_type.value in ("close", "trade"):
                    crit = next(
                        (
                            d
                            for d in qrep.diagnostics
                            if d.security_id == obs.security_id and d.rejects
                        ),
                        None,
                    )
                    raise SnapshotBuildError(
                        f"valuation-critical datum rejected for {obs.security_id}: "
                        f"{crit.message if crit else 'rejected'}"
                    )

        spots, quotes = self._assemble_spots(qrep.accepted)
        snap = MarketDataSnapshot(
            as_of=as_of,
            spots=spots,
            quotes=quotes,
            rates=dict(curves or {}),
            discount_factors=dict(discount_curves or {}),
            vol_surfaces=dict(vol_surfaces or {}),
            dividend_yields=dict(dividend_yields or {}),
            forwards=dict(forwards or {}),
            corporate_actions=dict(corporate_actions or {}),
            fx_provider=fx_provider,
            provenance=Provenance(source=self.source, observation_date=as_of, effective_date=as_of),
        )

        pit_probs = validate_pit(snap, max_staleness_days=policy.max_staleness_days)
        if pit_probs and policy.reject_look_ahead:
            if any("look-ahead" in p for p in pit_probs):
                raise SnapshotBuildError(f"PIT violation in assembled snapshot: {pit_probs[0]}")
        diags.extend(pit_probs)

        return BuildResult(
            snap, tuple(diags), tuple(qrep.accepted), norm.transform_log, snap.fingerprint()
        )

    def _assemble_spots(self, observations):
        """Latest accepted close/last per security → spot; bid/ask → MarketQuote."""
        spots: dict = {}
        quotes: dict = {}
        bids: dict = {}
        asks: dict = {}
        best_close: dict = {}
        for o in observations:
            if o.field in ("close", "last"):
                cur = best_close.get(o.security_id)
                if cur is None or (o.revision, o.observation_date) >= (
                    cur.revision,
                    cur.observation_date,
                ):
                    best_close[o.security_id] = o
            elif o.field == "bid":
                bids[o.security_id] = o.value
            elif o.field == "ask":
                asks[o.security_id] = o.value
        for sid, o in best_close.items():
            spots[sid] = o.value
        for sid in set(bids) | set(asks):
            quotes[sid] = MarketQuote(
                instrument_id=sid,
                value=spots.get(sid, 0.5 * (bids.get(sid, 0.0) + asks.get(sid, 0.0))),
                currency=(best_close.get(sid).currency if best_close.get(sid) else "USD") or "USD",
                bid=bids.get(sid),
                ask=asks.get(sid),
                provenance=Provenance(source="m19", observation_date=None),
            )
            if sid not in spots and bids.get(sid) and asks.get(sid):
                spots[sid] = 0.5 * (bids[sid] + asks[sid])
        return spots, quotes
