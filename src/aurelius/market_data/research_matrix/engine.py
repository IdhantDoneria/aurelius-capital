"""Point-in-Time Research Matrix Engine (AIDP Phase 6).

One PIT-safe accessor over the five certified engines. Given a date it returns a
survivorship-free universe (Phase 4) keyed by security_id, each row filled with
price (Phase 1), fundamental (Phase 3), and insider (Phase 5) features — every
field gated so knowledge_date ≤ as_of. Composition only: no data table, no new
PIT logic, no ticker join the sub-engines don't already own.

Identity: rows key on security_id. Each source resolves its own key from it —
price uses the PIT ticker SecurityMaster hands back in the universe row,
fundamentals use CIK (via cik_map, since filings are CIK-native and SecurityMaster
holds no CIK), insiders use security_id directly.

Caching: keyed by (as_of, universe_hash, feature_set, data_versions). Because all
five stores are append-only, per-source row counts are a monotonic data_version —
any ingest changes the count, changes the key, misses the cache. No manual bump.
"""

from __future__ import annotations

import hashlib
import statistics
from datetime import UTC, date, datetime

import pandas as pd

from aurelius.market_data.fundamentals.engine import CONCEPTS
from aurelius.market_data.research_matrix.feature_registry import FEATURES
from aurelius.market_data.research_matrix.schema import ResearchMatrix

# friendly fundamental inputs the registry's fundamental features need
_FUND_INPUTS = ("equity", "assets", "revenue", "net_income", "operating_cash_flow",
                "debt", "operating_income", "shares_outstanding")


class ResearchMatrixEngine:
    def __init__(self, *, universe, fundamentals, insiders, prices,
                 cik_map: dict[str, str] | None = None) -> None:
        self._universe = universe        # UniverseEngine (Phase 4)
        self._fundamentals = fundamentals  # FundamentalsEngine (Phase 3)
        self._insiders = insiders        # InsiderEngine (Phase 5)
        self._prices = prices            # PitPriceStore (Phase 1)
        self._cik_map = cik_map or {}
        self._cache: dict[tuple, ResearchMatrix] = {}

    # ── public API ──────────────────────────────────────────────────────────────

    def feature_matrix_as_of(self, as_of: date, universe: list[dict] | None = None,
                             features: list[str] | None = None) -> ResearchMatrix:
        """PIT research snapshot on `as_of`. `universe` defaults to the Phase 4
        survivorship-free universe; `features` defaults to the whole registry."""
        feats = list(features or FEATURES.keys())
        unknown = [f for f in feats if f not in FEATURES]
        if unknown:
            raise ValueError(f"unknown features: {unknown}")

        secs = universe if universe is not None else self._universe.universe_as_of(as_of).securities
        ids = [s["security_id"] for s in secs]

        dv = self._data_versions()
        key = (as_of.isoformat(), self._universe_hash(ids), tuple(sorted(feats)),
               tuple(sorted(dv.items())))
        if key in self._cache:
            return self._cache[key]

        needed = {FEATURES[f][0] for f in feats}
        # fundamentals via one set-based cross-section per input concept (the
        # store's factor-model path), NOT ~16 point queries per security.
        fund_xs = self._fund_cross_sections(as_of) if "fundamental" in needed else {}
        ins_xs = self._insider_signals(ids, as_of) if "insider" in needed else {}
        rows = []
        for s in secs:
            sid, tkr = s["security_id"], s.get("ticker")
            price = self._price_bundle(tkr, as_of) if ("price" in needed and tkr) else {}
            bundles = {
                "price": price,
                "fundamental": self._fund_bundle(sid, tkr, as_of, fund_xs, price) if "fundamental" in needed else {},
                "insider": ins_xs.get(sid, self._EMPTY_INSIDER) if "insider" in needed else {},
            }
            row = {"security_id": sid}
            for f in feats:
                src, field, _ = FEATURES[f]
                row[f] = bundles[src].get(field)
            rows.append(row)

        frame = pd.DataFrame(rows, columns=["security_id", *feats]).set_index("security_id")
        matrix = ResearchMatrix(
            as_of_date=as_of, universe_size=len(ids), data_versions=dv,
            generated_at=datetime.now(UTC), frame=frame,
            directions={f: FEATURES[f][2] for f in feats},
        )
        self._cache[key] = matrix
        return matrix

    # ── per-source bundles (one call per security per source) ────────────────────

    def _price_bundle(self, ticker: str, as_of: date) -> dict:
        w = self._prices.window_as_of(ticker, as_of)
        if not w:
            return {}
        closes = [float(b["close"]) for b in w]
        vols = [float(b["volume"]) for b in w]
        close, volume = closes[-1], vols[-1]
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]
        return {
            "close": close,
            "returns": (close / closes[0] - 1) if (len(closes) > 1 and closes[0]) else None,
            "volatility": statistics.pstdev(rets) if len(rets) >= 2 else None,
            "volume": volume,
            "dollar_volume": close * volume,
        }

    def _fund_cross_sections(self, as_of: date) -> dict[str, dict[str, float]]:
        """{input_name: {cik: value}} — one cross_section_as_of per candidate
        concept, higher-priority candidate winning per cik."""
        store = self._fundamentals._store  # noqa: SLF001
        out: dict[str, dict[str, float]] = {}
        for name in _FUND_INPUTS:
            m: dict[str, float] = {}
            for concept in reversed(CONCEPTS.get(name, [name])):
                m.update(store.cross_section_as_of(concept, as_of))
            out[name] = m
        return out

    def _fund_bundle(self, security_id: str, ticker: str | None, as_of: date,
                     fund_xs: dict, price: dict) -> dict:
        """Registry fundamental fields from the cross-sections. Same PIT gate and
        ratio math as FundamentalsEngine.factor_inputs_as_of, batched. market_cap
        reuses the already-computed PIT close (else one close_as_of)."""
        cik = self._cik_map.get(security_id)
        if cik is None:
            return {}
        g = lambda n: fund_xs[n].get(cik)  # noqa: E731
        equity, assets, revenue = g("equity"), g("assets"), g("revenue")
        ni, ocf, debt, op = g("net_income"), g("operating_cash_flow"), g("debt"), g("operating_income")
        shares = g("shares_outstanding")
        close = price.get("close")
        if close is None and ticker is not None:
            c = self._prices.close_as_of(ticker, as_of)
            close = float(c) if c is not None else None
        mc = shares * close if (shares is not None and close is not None) else None

        def div(a, b):
            return a / b if (a is not None and b not in (None, 0)) else None

        return {
            "market_cap": mc, "book_value": equity,
            "earnings_yield": div(ni, mc), "cash_flow_yield": div(ocf, mc),
            "roe": div(ni, equity), "roa": div(ni, assets),
            "operating_margin": div(op, revenue), "debt_to_equity": div(debt, equity),
        }

    _EMPTY_INSIDER = {"buy_value": 0.0, "sell_value": 0.0, "net_value": 0.0,
                      "insider_count": 0, "cluster_buy": False}

    def _insider_signals(self, ids: list[str], as_of: date) -> dict[str, dict]:
        """Batch insider signals (one gated query) → registry insider fields,
        applying the engine's cluster threshold. Matches InsiderEngine semantics."""
        threshold = self._insiders._cluster_threshold  # noqa: SLF001
        agg = self._insiders._store.signals_as_of(ids, as_of)  # noqa: SLF001
        out = {}
        for sid, a in agg.items():
            buyers = a["buyers"]
            out[sid] = {
                "buy_value": a["buy_value"], "sell_value": a["sell_value"],
                "net_value": a["buy_value"] - a["sell_value"],
                "insider_count": buyers, "cluster_buy": buyers >= threshold,
            }
        return out

    # ── determinism / caching ────────────────────────────────────────────────────

    @staticmethod
    def _universe_hash(ids: list[str]) -> str:
        h = hashlib.blake2b(digest_size=8)
        for sid in sorted(ids):
            h.update(sid.encode())
            h.update(b"\0")
        return h.hexdigest()

    def _data_versions(self) -> dict:
        """Append-only row counts per source = monotonic version signal."""
        return {
            "prices": self._count(self._prices, "raw_ohlcv"),
            "fundamentals": self._count(self._fundamentals._store, "fundamental_facts"),  # noqa: SLF001
            "insiders": self._count(self._insiders._store, "insider_transactions"),  # noqa: SLF001
        }

    @staticmethod
    def _count(store, table: str) -> int:
        with store._conn() as conn:  # noqa: SLF001 — read-only sibling access, matches Phase 4
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
