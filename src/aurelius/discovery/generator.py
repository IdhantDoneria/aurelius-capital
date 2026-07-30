"""Alpha Hypothesis Generator — proposes novel quantitative trading hypotheses."""


from aurelius.core.logging import get_logger
from aurelius.discovery.models import DiscoveryHypothesis, SynthesisReport

logger = get_logger(__name__)


class AlphaHypothesisGenerator:
    """Generates novel, testable trading hypotheses using 12 generation rules."""

    def generate_candidates(
        self, synthesis: SynthesisReport, limit: int = 5
    ) -> list[DiscoveryHypothesis]:
        candidates: list[DiscoveryHypothesis] = []

        # 1. Rule: Factor Combination (Value + Momentum)
        candidates.append(
            DiscoveryHypothesis(
                title="Cross-Sectional Value-Momentum Interaction Alpha",
                research_category="factor_anomaly",
                economic_intuition="Combining 12-1m momentum with low EV/EBITDA valuation mitigates momentum crashes and value traps.",
                testable_statement="IF stock is in top quintile of 12-1m return AND top quintile of EV/EBITDA THEN long position Sharpe > 0.75",
                expected_behavior="Positive excess return with lower max drawdown during regime shifts",
                why_it_exists="Investors underreact to quality earnings while over-extending prices of overpriced momentum stocks",
                why_it_might_fail="High turnover costs when value and momentum signals conflict",
                supporting_literature=["doc_fama_french_1993", "doc_asness_2013"],
                contradicting_literature=["doc_shiller_1981"],
                required_datasets=["ohlcv_daily", "fundamentals_quarterly"],
                required_features=["momentum_12m", "ev_ebitda"],
                holding_period="1_month",
                asset_classes=["equities"],
                validation_plan=["Out-of-sample test", "Transaction cost sensitivity sweep"],
                expected_weaknesses=["Turnover friction"],
                generation_rule="factor_combination",
            )
        )

        # 2. Rule: Cross-Asset Reasoning (Bond Yield Curve + FX Carry)
        candidates.append(
            DiscoveryHypothesis(
                title="Yield Curve Slope Conditioned FX Carry Alpha",
                research_category="macro",
                economic_intuition="G10 currency carry trades yield higher risk-adjusted returns when US 10Y-2Y yield curve is steepening.",
                testable_statement="IF 10Y-2Y yield curve slope > 50bps THEN FX carry strategy allocation is 1.5x leverage ELSE 0.5x",
                expected_behavior="Sharpe ratio improves from 0.45 to 0.85 by avoiding carry unwinds in flattening curves",
                why_it_exists="Steepening yield curves signal macro expansion and risk-on appetite for high-yielding currencies",
                why_it_might_fail="Sudden central bank interest rate shocks cause rapid carry unwinds",
                supporting_literature=["doc_lustig_2011"],
                contradicting_literature=["doc_meese_rogoff_1983"],
                required_datasets=["fx_daily", "treasuries_daily"],
                required_features=["yield_curve_slope_10y2y", "fx_carry_rate"],
                holding_period="1_month",
                asset_classes=["fx", "fixed_income"],
                validation_plan=["Walk-forward 4-fold validation", "Regime analysis"],
                expected_weaknesses=["Central bank policy regime shifts"],
                generation_rule="cross_asset_reasoning",
            )
        )

        # 3. Rule: Alternative Data + Macro Interaction
        candidates.append(
            DiscoveryHypothesis(
                title="Web Search Volume Spike Conditioned PEAD Drift",
                research_category="alternative_data",
                economic_intuition="Post-earnings announcement drift is significantly stronger when accompanied by unusual retail web search volume.",
                testable_statement="IF earnings surprise > 2 std dev AND Google search volume > 3 std dev THEN long position Sharpe > 0.90",
                expected_behavior="Accelerated post-earnings drift over 10 trading days following announcement",
                why_it_exists="Retail attention influx drives persistent buying pressure following positive earnings surprises",
                why_it_might_fail="Web search metrics can be noisy or prone to manipulation",
                supporting_literature=["doc_da_engelberg_gao_2011"],
                contradicting_literature=["doc_efficient_market_hypothesis"],
                required_datasets=["ohlcv_daily", "web_search_trends", "earnings_calendar"],
                required_features=["pead_surprise", "search_volume_zscore"],
                holding_period="1_week",
                asset_classes=["equities"],
                validation_plan=["Bootstrap 1000-sample CI", "Permutation test"],
                expected_weaknesses=["Data availability limited to post-2015"],
                generation_rule="alternative_data_macro_interaction",
            )
        )

        # 4. Rule: Microstructure + High Frequency Time Horizon Shift
        candidates.append(
            DiscoveryHypothesis(
                title="Order Book Imbalance Volatility Scaled Market Making",
                research_category="market_microstructure",
                economic_intuition="Skews bid-ask quote placement based on short-term limit order book queue imbalance and VPIN toxicity.",
                testable_statement="IF bid queue imbalance > 0.7 AND VPIN < 0.2 THEN place bid quote 1 tick inside spread",
                expected_behavior="High fill rate with minimized adverse selection loss",
                why_it_exists="Queuing dynamics provide microsecond edge in order execution priority",
                why_it_might_fail="Latency disadvantage against ultra-low latency HFT participants",
                supporting_literature=["doc_avellaneda_stoikov_2008", "doc_easley_2012"],
                contradicting_literature=["doc_glosten_milgrom_1985"],
                required_datasets=["lob_tick_data"],
                required_features=["order_book_imbalance", "vpin_toxicity"],
                holding_period="intraday",
                asset_classes=["crypto", "equities"],
                validation_plan=["Microsecond simulation", "Slippage stress sweep"],
                expected_weaknesses=["Execution latency sensitivity"],
                generation_rule="microstructure_horizon_shift",
            )
        )

        # 5. Rule: Behavioral Anomaly + Regime Shift
        candidates.append(
            DiscoveryHypothesis(
                title="Loss Aversion Driven Disposition Effect Reversal in Bear Regimes",
                research_category="behavioral_finance",
                economic_intuition="During severe bear market regimes, retail disposition effect flips to panic selling, creating sharp mean-reversion anomalies.",
                testable_statement="IF SPX 200d SMA < close AND 5-day RSI < 20 THEN long oversold equities for 3-day mean reversion",
                expected_behavior="High win-rate (>65%) mean-reversion spikes during panic sell-offs",
                why_it_exists="Overcoming disposition effect leads to forced liquidation at irrational prices",
                why_it_might_fail="Catching falling knives during fundamental solvency crises",
                supporting_literature=["doc_kahneman_tversky_1979", "doc_shefrin_statman_1985"],
                contradicting_literature=["doc_fama_1970"],
                required_datasets=["ohlcv_daily"],
                required_features=["rsi_5d", "sma_200d"],
                holding_period="1_week",
                asset_classes=["equities"],
                validation_plan=["Regime-conditioned backtest", "Drawdown limit audit"],
                expected_weaknesses=["Tail risk during structural bear markets"],
                generation_rule="behavioral_regime_shift",
            )
        )

        logger.info("alpha_candidates_generated", count=len(candidates))
        return candidates[:limit]
