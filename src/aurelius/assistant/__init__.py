"""AI Quant Research Assistant (Phase 10).

    from aurelius.assistant import ResearchAssistant

    ai = ResearchAssistant()                       # offline, deterministic
    summary = ai.read_paper(open("paper.txt").read())
    hyps = ai.generate_hypotheses(summary, "jdoe")
    review = ai.review_code(open("strategy.py").read())
    print(ai.write_report(experiment_record, code_review=review))

Inject an LLM to enrich prose: `ResearchAssistant(llm=my_client)` where
my_client is `Callable[[str], str]`. The assistant assists a human; it holds no
capital and imports no execution path, so it cannot trade.
"""

from aurelius.assistant.assistant import (
    BiasReport,
    CodeFinding,
    CodeReview,
    LLMClient,
    PaperSummary,
    ResearchAssistant,
)

__all__ = [
    "BiasReport",
    "CodeFinding",
    "CodeReview",
    "LLMClient",
    "PaperSummary",
    "ResearchAssistant",
]


def demo() -> None:
    """Deterministic offline self-check across every capability."""
    from datetime import UTC, datetime

    from aurelius.research.models import ExperimentRecord, ValidationReport, Verdict

    ai = ResearchAssistant()

    paper = (
        "Time-Series Momentum in Equity Index Futures\n"
        "Abstract: We document that past 12-month returns predict future returns. "
        "A momentum strategy delivers significant abnormal returns and outperforms "
        "the market across 58 instruments.\n"
        "Introduction: Prices trend.\n"
    )
    summary = ai.read_paper(paper)
    assert "momentum" in summary.title.lower()
    assert summary.claims, "should extract at least one empirical claim"
    assert "momentum" in summary.keywords

    hyps = ai.generate_hypotheses(summary, "jdoe")
    assert hyps
    assert hyps[0].statement.lower().startswith("test whether")

    bad_code = (
        "def signal(df):\n"
        "    df['future'] = df['close'].shift(-1)   # peeks ahead\n"
        "    z = (df['close'] - df['close'].mean()) / df['close'].std()\n"
        "    return z\n"
    )
    review = ai.review_code(bad_code)
    assert review.has_lookahead, "negative shift must be flagged"

    report = ValidationReport(
        verdict=Verdict.REJECT,
        reasons=["OOS Sharpe below floor"],
        is_sharpe=1.8,
        oos_sharpe=0.2,
        oos_return=0.03,
        oos_max_drawdown=-0.15,
        oos_trades=12,
        n_trials=40,
        adjusted_pvalue=0.42,
        param_cv=1.1,
        checks={"oos": False},
    )
    explanation = ai.explain_results(report)
    assert "REJECT" in explanation

    biases = ai.detect_biases(report, oos_observations=12, code_review=review)
    assert biases.flags["overfitting"]
    assert biases.flags["data_mining"]
    assert biases.flags["small_sample"]
    assert biases.flags["look_ahead"]

    record = ExperimentRecord(
        id="exp-abc123",
        hypothesis_id=hyps[0].id,
        researcher="jdoe",
        created_at=datetime(2026, 7, 27, tzinfo=UTC),
        dataset_version="ds-deadbeef",
        strategy_name="TSMomentum",
        strategy_version=3,
        features_used=["ret_12m", "vol_20d"],
        params={"lookback": 252},
        report=report,
    )
    md = ai.write_report(record, oos_observations=12, code_review=review)
    assert "# Research Report" in md
    assert "cannot trade" in md

    print("assistant demo ok:", hyps[0].statement[:60])


if __name__ == "__main__":
    demo()
