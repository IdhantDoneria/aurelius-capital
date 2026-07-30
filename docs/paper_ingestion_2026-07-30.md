# Paper Ingestion — 2026-07-30

Batch of 9 seminal quant-finance papers requested for `research_corpus/incoming/`. 8 of 9 downloaded and verified; 1 skipped (see below).

## Delivered

All files verified by extracting page-1 text and confirming title/author match.

| Paper | Filename |
|---|---|
| Fama & French (1993) | `Fama_French_1993_Common_Risk_Factors_in_the_Returns_on_Stocks_and_Bonds.pdf` |
| Carhart (1997) | `Carhart_1997_On_Persistence_in_Mutual_Fund_Performance.pdf` |
| Jegadeesh & Titman (1993) | `Jegadeesh_Titman_1993_Returns_to_Buying_Winners_and_Selling_Losers.pdf` |
| Novy-Marx (2013) | `Novy_Marx_2013_The_Other_Side_of_Value_Gross_Profitability_Premium.pdf` |
| Sharpe (1964) | `Sharpe_1964_Capital_Asset_Prices_A_Theory_of_Market_Equilibrium.pdf` |
| Black & Litterman (1992) | `Black_Litterman_1992_Global_Portfolio_Optimization.pdf` |
| Gatev, Goetzmann & Rouwenhorst | `Gatev_Goetzmann_Rouwenhorst_Pairs_Trading_Performance_of_a_Relative_Value_Arbitrage_Rule.pdf` |
| Asness, Moskowitz & Pedersen (2013) | `Asness_Moskowitz_Pedersen_2013_Value_and_Momentum_Everywhere.pdf` |

## Known limitations / Skipped

**Item skipped:** Markowitz (1952), "Portfolio Selection" (*The Journal of Finance*, Vol. 7, No. 1).

**Reason (impossibility, not effort):** Every source attempted was unreachable or paywalled from this sandbox's network egress:
- `finance.martinsewell.com/capm/Markowitz1952.pdf` (primary) — connection timeout on 3 separate attempts (both http and https).
- `www.math.hkust.edu.hk/~maykwok/courses/ma362/07F/markowitz_JF.pdf` — server returns 403 Forbidden (hotlink/referer block), confirmed with two different Referer headers.
- `www.math.hkust.hk/~maykwok/...` (alternate host spelling) — DNS resolution failure.
- `web.archive.org` mirror of the martinsewell URL — blocked by this environment's URL policy (`cowork_web_fetch_url_blocked`), and bash-level access to archive.org is disallowed per the same web-content restriction.
- `raw.githubusercontent.com/yangyutu/FinancialResearch/...` — repo does not contain this paper (confirmed via GitHub API directory listing).
- Wiley Online Library (official publisher) — paywalled, no open PDF.
- ResearchGate / Scribd copies — require login, not a direct downloadable PDF.

**What would unblock it:** Any one of — (a) sandbox network access to `finance.martinsewell.com` or `math.hkust.edu.hk` restored/whitelisted, (b) a valid institutional/Wiley or JSTOR credential to pull the official version, or (c) the user manually downloading the PDF from any of the above sources and dropping it into `research_corpus/incoming/` for renaming.
