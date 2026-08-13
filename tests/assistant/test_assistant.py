"""Phase-10 AI Research Assistant tests: parsing, hypotheses, review, biases, report."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mentisrex.assistant import ResearchAssistant
from mentisrex.research.models import ExperimentRecord, ValidationReport, Verdict

PAPER = (
    "Betting Against Beta\n"
    "Abstract: We find that low-beta assets deliver significant abnormal returns "
    "and outperform high-beta assets on a risk-adjusted basis.\n"
    "Introduction: Leverage constraints drive the anomaly.\n"
)


def _report(**kw) -> ValidationReport:
    base = {
        "verdict": Verdict.REJECT,
        "reasons": [],
        "is_sharpe": 1.5,
        "oos_sharpe": 0.3,
        "oos_return": 0.04,
        "oos_max_drawdown": -0.1,
        "oos_trades": 50,
        "n_trials": 1,
        "adjusted_pvalue": 0.01,
        "param_cv": 0.2,
        "checks": {},
    }
    base.update(kw)
    return ValidationReport(**base)  # type: ignore[arg-type]


# ── read_paper ──────────────────────────────────────────────────────────────


def test_read_paper_extracts_title_and_claims():
    ai = ResearchAssistant()
    s = ai.read_paper(PAPER)
    assert s.title == "Betting Against Beta"
    assert any("abnormal returns" in c.lower() for c in s.claims)
    assert "beta" in s.keywords


def test_read_paper_empty_is_safe():
    s = ResearchAssistant().read_paper("")
    assert s.title == "(untitled)"
    assert s.claims == []


# ── generate_hypotheses ───────────────────────────────────────────────────────


def test_generate_hypotheses_are_testable():
    ai = ResearchAssistant()
    hyps = ai.generate_hypotheses(ai.read_paper(PAPER), "quant1")
    assert hyps
    assert all(h.statement.lower().startswith("test whether") for h in hyps)
    assert all(h.researcher == "quant1" for h in hyps)


# ── review_code ───────────────────────────────────────────────────────────────


def test_review_flags_negative_shift_lookahead():
    r = ResearchAssistant().review_code("y = df['close'].shift(-1)\n")
    assert r.has_lookahead
    assert r.findings[0].severity == "high"


def test_review_flags_full_series_scaler_leakage():
    r = ResearchAssistant().review_code("scaler = StandardScaler().fit(X)\n")
    assert any("leakage" in f.issue.lower() for f in r.findings)


def test_review_ignores_comments():
    r = ResearchAssistant().review_code("# df['x'].shift(-1) is bad, don't do it\n")
    assert r.findings == []


def test_clean_code_has_no_findings():
    r = ResearchAssistant().review_code("z = df['close'].pct_change().shift(1)\n")
    assert r.findings == []


# ── detect_biases ─────────────────────────────────────────────────────────────


def test_detect_overfitting_and_data_mining():
    rep = _report(param_cv=1.2, n_trials=50, adjusted_pvalue=0.6)
    b = ResearchAssistant().detect_biases(rep)
    assert b.flags["overfitting"]
    assert b.flags["data_mining"]


def test_detect_small_sample():
    b = ResearchAssistant().detect_biases(_report(), oos_observations=5)
    assert b.flags["small_sample"]


def test_clean_report_trips_no_statistical_bias():
    b = ResearchAssistant().detect_biases(_report(), oos_observations=100)
    assert not b.flags["overfitting"]
    assert not b.flags["data_mining"]
    assert not b.flags["small_sample"]
    assert b.notes  # survivorship reminder always present


def test_lookahead_flag_wired_from_code_review():
    ai = ResearchAssistant()
    review = ai.review_code("f = df['close'].shift(-1)\n")
    b = ai.detect_biases(_report(), oos_observations=100, code_review=review)
    assert b.flags["look_ahead"]


# ── explain + report ──────────────────────────────────────────────────────────


def test_explain_results_mentions_verdict():
    txt = ResearchAssistant().explain_results(_report(verdict=Verdict.ACCEPT))
    assert "ACCEPT" in txt


def test_write_report_is_markdown_and_advisory():
    ai = ResearchAssistant()
    rec = ExperimentRecord(
        id="exp-1",
        hypothesis_id="h1",
        researcher="quant1",
        created_at=datetime(2026, 7, 27, tzinfo=UTC),
        dataset_version="ds-1",
        strategy_name="BAB",
        strategy_version=1,
        features_used=["beta"],
        params={"lookback": 252},
        report=_report(),
    )
    md = ai.write_report(rec)
    assert md.startswith("# Research Report")
    assert "cannot trade" in md


# ── LLM injection seam ────────────────────────────────────────────────────────


def test_llm_client_is_used_when_injected():
    calls = []

    def fake_llm(prompt: str) -> str:
        calls.append(prompt)
        return "ENRICHED"

    ai = ResearchAssistant(llm=fake_llm)
    s = ai.read_paper(PAPER)
    assert s.llm_summary == "ENRICHED"
    assert calls  # the seam actually fired


def test_assistant_cannot_trade_by_construction():
    # Parse the module's imports (not its prose) and assert no execution path is
    # pulled in — this is what enforces "AI assists, AI does not trade".
    import ast

    import mentisrex.assistant.assistant as mod

    tree = ast.parse(open(mod.__file__).read())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported += [n.name for n in node.names]

    forbidden = ("broker", "oms", "execution", "order")
    for mod_name in imported:
        assert not any(f in mod_name.lower() for f in forbidden), (
            f"assistant must not import an execution path: {mod_name}"
        )


def test_demo_self_check():
    from mentisrex.assistant import demo

    demo()


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
