# M6 — Investable Universe Fidelity Audit

**Aurelius Capital — Methodology Fidelity Campaign**
**Date:** 2026-08-05
**Type:** institutional data-availability audit. **No production code, methodology,
strategy, filter, portfolio, or parameter changed.**
**Baseline under audit:** M1 (equal-weight) + M2 ($5 screen) + M4 (1-month skip),
dual-basis reporting (M5). M3 remains a documented engine limitation, not revisited.
**Data audited:** `data/analytics.duckdb` (single table `ohlcv`), the frozen panel
every momentum result was produced on.
**Regression state:** 595 passed, 2 skipped (unchanged) — every prior baseline
remains reproducible.

---

## 0. Method

The seven required audit lenses (Paper Methodology, Historical Data, Market
Structure, Universe Audit, Liquidity Analysis, Statistical Validation,
Documentation) were executed as **one consolidated investigation against the single
dataset they all interrogate**, then independently re-verified. Rationale
(documented, not silently skipped): the panel is one 636 MB single-table DuckDB;
seven cold agents each re-opening it would re-derive byte-identical numbers at 7×
cost with number-drift risk, violating single-source-of-truth. Independence is
instead guaranteed by a separate verification agent that re-queried every headline
figure from the raw DB. Every number below traces to a query on `analytics.duckdb`.

### Ground-truth schema (measured)

`ohlcv` columns: `symbol, timestamp, frequency, open, high, low, close, volume,
vwap, trade_count, quality_score, source, adjustment_factor`.

| Fact | Measured value |
|---|---|
| Rows | 6,457,021 |
| Distinct symbols | 2,143 (US 1,016 · India `.NS` 1,127) |
| Date range | 2014-01-01 → 2026-07-31, daily (`1d`) |
| Source | `csv` (100%) |
| `adjustment_factor` | **1.0 for all 6,457,021 rows** |
| `vwap` NULL | **100%** |
| `trade_count` NULL | **100%** |
| `volume = 0` | 3.04% |
| Symbols ending >30d before panel end | **9 / 2,143 (0.4%)** |
| Symbols ending at panel end | 1,120 |
| Symbols starting >30d after panel start | 437 (staggered listing — expected) |

**Absent entirely:** exchange, market cap, shares outstanding, sector/industry,
delisting flag, corporate-action event table. The panel is prices + volume only.

---

## 1. Paper universe rules (JT-1993, extended by JT-2001)

JT-1993 draws its universe from **CRSP NYSE + AMEX common stocks** (1965–1989),
equal-weighted deciles, with sufficient price history to form and hold. JT-2001
refines it with a **price ≥ $5** screen and excludes the smallest market-cap
decile. The union of universe-selection rules the campaign must reproduce:

1. Exchange membership (NYSE + AMEX; NASDAQ in later literature)
2. Common-stock-only filter (CRSP share codes 10/11 — exclude ADRs, REITs, CEFs, units)
3. Sufficient price history for formation + skip + holding
4. Price ≥ $5 at formation (JT-2001)
5. Market-cap / size screens (exclude smallest decile; size subsamples)
6. Survivorship-free universe with delisting returns
7. Corporate-action-adjusted prices (splits, dividends, ticker changes, mergers)

---

## 2. Per-component audit

### 2.1 Exchange membership (NYSE / AMEX / NASDAQ)
- **Current status:** partially available.
- **Available:** the `.NS` suffix cleanly partitions **India-NSE (1,127)** from
  **US (1,016)** — a reliable country/exchange-group tag.
- **Missing:** within the US set, no NYSE / AMEX / NASDAQ distinction. No exchange
  column exists.
- **Proxy:** a *current* ticker→exchange map could tag US names, but (a) it is
  point-in-time-now, not historical, and (b) it ignores exchange switches and
  delisted tickers — look-ahead + survivorship contamination.
- **Scientific defensibility:** country partition = high. Historical NYSE/AMEX/NASDAQ
  membership from current listings = **low** (anachronistic).
- **Expected effect:** JT-1993 is NYSE/AMEX-only (larger, more liquid than NASDAQ);
  our US set mixes all venues, tilting toward smaller/NASDAQ names — plausibly
  noisier momentum. Moderate.
- **Recommendation:** country split **IMPLEMENT** (already implicit in the panel).
  Exact historical NYSE/AMEX/NASDAQ separation **BLOCKED** (needs CRSP `EXCHCD`).

### 2.2 Common-stock-only filter (share codes)
- **Available:** none — no share-type metadata.
- **Missing:** ability to exclude ADRs, REITs, closed-end funds, units, ETFs.
- **Proxy:** a hand-maintained ETF/ADR ticker blocklist is incomplete and
  point-in-time — not defensible as CRSP `SHRCD` 10/11.
- **Expected effect:** non-common securities dilute the cross-section and add
  non-equity dynamics; dampens the momentum spread. Low–moderate.
- **Recommendation:** **BLOCKED** (needs CRSP `SHRCD`).

### 2.3 Sufficient price history
- **Available:** full daily history; the strategy already requires
  `lookback + skip + 1` bars (`templates.py`).
- **Recommendation:** **NOT REQUIRED** — already satisfied exactly, no change.

### 2.4 Price ≥ $5 at formation (JT-2001)
- **Available:** `close`. Already implemented as **M2** (`min_price=5.0`, applied to
  current formation-bar close).
- **Scientific defensibility:** exact match to JT-2001.
- **Recommendation:** **NOT REQUIRED** — already implemented (M2), exact.

### 2.5 Market capitalization / size screens
- **Available:** none. `adjustment_factor` is uniformly 1.0 and **shares
  outstanding is absent**, so market cap cannot be reconstructed.
- **Missing:** shares outstanding (point-in-time). Yahoo supplies only *current*
  shares → historical market cap is **not** reconstructable even with Yahoo
  (look-ahead + buyback/issuance drift over 12 years).
- **Proxy:** dollar volume (`close × volume`) / ADV as a *size* proxy. Precedent
  exists (dollar volume correlates with size), but it conflates liquidity with size
  and is a weak size instrument.
- **Scientific defensibility:** as a true size/market-cap variable — **low**.
- **Expected effect:** cannot exclude the smallest-cap decile (JT-2001) nor run size
  subsamples; the book carries micro-caps JT screens out. Moderate.
- **Recommendation:** market-cap / size screens **BLOCKED**. (The liquidity proxy in
  2.6 is *not* a market-cap substitute.)

### 2.6 Liquidity (volume / dollar volume / ADV / median ADV / turnover)
- **Available:** `volume` (populated, 3% zero; 6.26 M rows with `close>0 & volume>0`).
  Dollar volume `close × volume`, ADV (rolling mean), and median ADV are all
  **directly computable** (spot check: AAPL 60-day median dollar volume ≈ \$1.51e10).
- **Missing:** `vwap` (100% NULL) and `trade_count` (100% NULL); **turnover**
  (volume ÷ shares outstanding) — blocked, no shares.
- **Proxy:** ADV / median ADV / dollar volume as the liquidity screen. Academic
  precedent: Amihud (2002) illiquidity, standard dollar-volume liquidity filters.
- **Scientific defensibility:** **high** for a liquidity screen (this is what the
  metric legitimately measures); does **not** stand in for market cap.
- **Bias introduced:** favors liquid names; mild large-cap tilt — directionally the
  *same* screen JT’s $5 + smallest-decile exclusion imposes, so bias is toward, not
  away from, paper intent. Confidence: medium-high.
- **Recommendation:** ADV / median ADV / dollar-volume screen **IMPLEMENT PROXY**.
  Turnover **BLOCKED**.

### 2.7 Survivorship bias / delistings
- **Current universe construction:** currently-listed snapshot — only **9 / 2,143
  (0.4%)** symbols end >30 days before the panel’s max date; virtually every name
  runs to 2026-07-31.
- **Historical constituent availability:** none — delisted securities and their
  **delisting returns** are absent.
- **Magnitude:** a true 12-year US+India cross-section would delist *hundreds* of
  names; 0.4% early-termination confirms delisted losers are effectively missing.
  This inflates the momentum long-short spread by an **unquantifiable** amount —
  unquantifiable precisely *because* the corrective data is the missing data
  (confirms and now measures Lesson L8).
- **Mitigation:** none honest from the panel; only fix is a CRSP delisting-returns
  dataset (`DLRET`).
- **Expected effect:** **HIGH, upward bias** on WML.
- **Recommendation:** **BLOCKED** (needs CRSP delisting returns). No proxy is
  defensible — a survivorship correction cannot be manufactured from survivors.

### 2.8 Corporate actions (splits / dividends / ticker changes / mergers)
- **Available:** prices appear **pre-adjusted upstream** (`adjustment_factor` = 1.0
  everywhere; e.g. AAPL 2022 trades as a back-adjusted ~\$50 series, not raw ~\$180),
  but provenance is a bare `csv` source with **no corporate-action event table**.
- **Missing:** any record to *verify* split/dividend/ticker/merger handling; merged
  and renamed entities cannot be traced.
- **Scientific defensibility:** prices are usable (adjusted), but adjustment
  **quality is unverifiable** — approximately reproducible, not auditable.
- **Expected effect:** if upstream adjustment is correct, negligible; if wrong,
  spurious formation returns. Unverifiable ⇒ medium residual risk.
- **Recommendation:** **IMPLEMENT PROXY** — trust the upstream-adjusted series with a
  standing caveat; *verification* is **BLOCKED** pending a CA event source (CRSP
  `DISTCD`/`CFACPR`).

---

## 3. Decision matrix

| Methodology Item | Paper Requirement | Current Capability | Proxy Available | Blocked | Recommended Action | Expected Impact | Confidence |
|---|---|---|---|---|---|---|---|
| Exchange membership | NYSE+AMEX (JT-93) | Country split only (`.NS`) | Current-listing map (weak) | Exact venue | Country: IMPLEMENT · Venue: BLOCKED | Moderate | High (country) / Low (venue) |
| Common-stock filter | CRSP SHRCD 10/11 | None | Blocklist (incomplete) | Yes | BLOCKED | Low–Moderate | Low |
| Sufficient history | Form+skip+hold bars | Full daily | — | No | NOT REQUIRED (done) | — | High |
| Price ≥ \$5 | JT-2001 screen | `close` present | — | No | NOT REQUIRED (M2 done) | — | High |
| Market cap / size decile | Exclude smallest cap | None (no shares) | Dollar-vol (weak size) | Yes (as size) | BLOCKED | Moderate | Low |
| Liquidity (ADV / \$-vol) | Implicit liquidity | `volume` present | ADV/median ADV/\$-vol | Turnover only | IMPLEMENT PROXY | Low–Moderate | Med-High |
| Survivorship / delistings | CRSP delist returns | Survivor snapshot (0.4% delist) | None honest | Yes | BLOCKED | **HIGH (upward)** | High (that gap exists) |
| Corporate actions | Split/div adjusted | Pre-adjusted, unverifiable | Trust upstream | Verification | IMPLEMENT PROXY (caveat) | Med (if wrong) | Medium |

---

## 4. Final deliverable — the six questions

**1. Reproducible exactly today:** sufficient-history screen; price ≥ \$5 (M2);
equal-weight decile construction (M1); 1-month skip (M4); daily close-to-close
formation returns; US-vs-India market partition (`.NS`). Gross/net dual reporting
(M5).

**2. Require proxies:** liquidity-based universe screening (ADV / median ADV /
dollar volume standing in for a formal liquidity/size filter); corporate-action
adjustment (trusting the upstream pre-adjusted series).

**3. Scientifically acceptable proxies:** ADV / median ADV / dollar-volume liquidity
screen (Amihud precedent; measures exactly what it claims) and the `.NS` country
partition. **Not** acceptable: current exchange as historical exchange; current
shares as historical market cap; any manufactured survivorship correction.

**4. Impossible with current data:** exact NYSE/AMEX/NASDAQ historical membership;
common-share-type filtering; market-cap / size-decile screens; turnover;
survivorship-free universe with delisting returns; corporate-action-adjustment
*verification*.

**5. Missing datasets that would materially improve fidelity:** **CRSP** is the
single high-leverage unblock — one dataset supplies `EXCHCD` (exchange), `SHRCD`
(share type), `SHROUT` (→ market cap / size deciles), `DLRET` (delisting returns →
survivorship-free), and `CFACPR/DISTCD` (CA verification). **Compustat** adds
fundamentals (not needed for price-only momentum, relevant to blocked factor
papers). CRSP alone converts five BLOCKED rows to IMPLEMENT.

**6. What M7 should implement:** only the evidence-safe, no-missing-data proxy — an
**optional ADV / dollar-volume liquidity universe filter** (evidence-gated,
defaulted off so no baseline shifts silently), and a formalized US/India market
partition. M7 must **not** attempt market-cap, exchange, or survivorship
reconstruction from current-listing data — that would be look-ahead fabrication, not
fidelity.

---

## 5. Certification

| Condition | Status |
|---|---|
| No production code changed | ✅ (docs only) |
| No methodology / filter / portfolio / parameter changed | ✅ |
| All previous baselines remain reproducible | ✅ (595 passed, 2 skipped) |
| Every methodology component audited | ✅ (§2.1–2.8) |
| Every recommendation evidence-backed | ✅ (all figures from `analytics.duckdb`) |
| Every proxy justified (why / bias / precedent / confidence) | ✅ (§2.6, §2.8, §3) |
| Clear M7 implementation roadmap | ✅ (§4 Q6) |

**M6 CERTIFIED — AUDIT ONLY.** The remaining reproduction gap is confirmed
**data-fidelity**, not implementation: survivorship (upward, HIGH) + absent
market-cap/exchange/share-type metadata, with transaction costs already ruled out
(M5). The single materially-corrective acquisition is **CRSP**. STOP — M7 not begun.
