"""AI Quant Research Assistant — helps researchers, never trades.

The assistant is read-only over research artifacts (papers, ValidationReports,
strategy source). It deliberately imports nothing from paper/, backtesting.oms/
or any execution path, so by construction it *cannot* place an order — the
"AI assists, AI does not trade" rule is enforced structurally, not by a flag.

The "AI" is an injected, optional LLM: `LLMClient = Callable[[str], str]`
(prompt -> completion). Everything works offline with no LLM — the deterministic
analyzers below do the mechanical/statistical work (section parsing, bias
statistics, code smells, report assembly) that does not need a model. When an
LLM client is supplied, methods enrich their output with its prose. This keeps
the module dependency-free, testable, and honest about what is heuristic vs.
model-generated.

ponytail: paper "reading" is plaintext section/claim extraction, not a PDF
parser or an embeddings index. Wire a real parser/RAG when researchers actually
feed PDFs at volume.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from aurelius.research.models import (
    ExperimentRecord,
    Hypothesis,
    ValidationCriteria,
    ValidationReport,
    Verdict,
)

LLMClient = Callable[[str], str]  # prompt -> completion; the only "AI" seam

# words that mark a sentence as an empirical claim worth turning into a hypothesis
_CLAIM_MARKERS = (
    "we find",
    "we show",
    "we document",
    "outperform",
    "significant",
    "predict",
    "premium",
    "anomaly",
    "abnormal return",
    "excess return",
    "alpha",
    "forecast",
)
_STOPWORDS = frozenset(
    "the a an of to in and or for is are we our this that with on by as at from be "
    "these those it its their they can using use based over under into than then "
    "which has have had not but also more most any all each per".split()
)


@dataclass
class PaperSummary:
    title: str
    abstract: str
    claims: list[str]
    keywords: list[str]
    llm_summary: str = ""


@dataclass
class CodeFinding:
    line: int
    severity: str  # high | medium | low
    issue: str
    fix: str


@dataclass
class CodeReview:
    findings: list[CodeFinding]
    llm_notes: str = ""

    @property
    def has_lookahead(self) -> bool:
        return any("look-ahead" in f.issue.lower() for f in self.findings)


@dataclass
class BiasReport:
    flags: dict[str, bool]  # bias name -> tripped?
    notes: list[str] = field(default_factory=list)

    @property
    def any_tripped(self) -> bool:
        return any(self.flags.values())


# ── static code-review rules for common quant look-ahead / leakage bugs ────────
# (compiled regex, severity, issue, fix). Curated + conservative: better to miss
# than to drown a reviewer in false positives.
_CODE_RULES: list[tuple[re.Pattern[str], str, str, str]] = [
    (
        re.compile(r"\.shift\(\s*-\d+"),
        "high",
        "look-ahead: negative shift pulls FUTURE bars into a feature",
        "shift by a positive amount so features only use past data",
    ),
    (
        re.compile(r"\[\s*i\s*\+\s*\d+\s*\]|\.iloc\[\s*i\s*\+"),
        "high",
        "look-ahead: indexing i+k reads a bar that has not happened yet",
        "use i or i-k; the signal at bar i may only use data up to i",
    ),
    (
        re.compile(r"(scaler|StandardScaler|MinMaxScaler)[^\n]*\.fit\("),
        "high",
        "leakage: scaler fit on the full series leaks test-set statistics",
        "fit the scaler on train only, then transform test",
    ),
    (
        re.compile(r"\.fillna\(\s*method\s*=\s*['\"]bfill|\.bfill\("),
        "medium",
        "look-ahead: backfill copies future values backward",
        "forward-fill (ffill) or drop; never backfill a time series feature",
    ),
    (
        re.compile(r"\b(df|data|prices)\b[^\n]*\.(max|min|mean|std|quantile)\(\)"),
        "medium",
        "look-ahead: a whole-series statistic uses the future for a point-in-time feature",
        "use an expanding/rolling window so each point sees only its past",
    ),
    (
        re.compile(r"resample\("),
        "low",
        "check alignment: resample can label a bar with its right edge (future close)",
        "set label='left'/closed='left' or lag one bar",
    ),
    (
        re.compile(r"random_state\s*=\s*None|shuffle\s*=\s*True"),
        "medium",
        "reproducibility/leakage: shuffling time-series folds breaks temporal order",
        "use a fixed seed and time-ordered (walk-forward) splits, never shuffle",
    ),
]


class ResearchAssistant:
    """Read-only helper for a human researcher. Owns no capital, no broker."""

    def __init__(
        self,
        llm: LLMClient | None = None,
        criteria: ValidationCriteria | None = None,
    ) -> None:
        self._llm = llm
        self._criteria = criteria or ValidationCriteria()

    # ── 1. read research papers ────────────────────────────────────────────────

    def read_paper(self, text: str) -> PaperSummary:
        """Extract title/abstract/claims/keywords from a plaintext paper."""
        lines = [ln.strip() for ln in text.splitlines()]
        title = next((ln for ln in lines if ln), "(untitled)")
        abstract = self._section(text, "abstract")
        claims = self._extract_claims(text)
        keywords = self._keywords(text)
        llm_summary = ""
        if self._llm is not None:
            llm_summary = self._llm(
                "Summarize this quant finance paper in 3 sentences for a "
                f"researcher deciding whether to test it:\n\n{text[:6000]}"
            )
        return PaperSummary(title[:200], abstract, claims, keywords, llm_summary)

    # ── 2. generate hypotheses ──────────────────────────────────────────────────

    def generate_hypotheses(
        self,
        summary: PaperSummary,
        researcher: str,
        limit: int = 5,
    ) -> list[Hypothesis]:
        """Turn a paper's claims into testable Hypothesis records (reuses Phase-6)."""
        now = datetime.now(UTC)
        out: list[Hypothesis] = []
        for claim in summary.claims[:limit]:
            statement = self._as_testable(claim)
            hid = hashlib.sha256(f"{statement}|{researcher}".encode()).hexdigest()[:12]
            out.append(
                Hypothesis(
                    id=hid,
                    statement=statement,
                    rationale=f"Derived from paper '{summary.title}': {claim}",
                    researcher=researcher,
                    created_at=now,
                )
            )
        if self._llm is not None and summary.claims:
            extra = self._llm(
                "Propose one additional, falsifiable trading hypothesis implied by "
                f"but not stated in these claims:\n{summary.claims}"
            ).strip()
            if extra:
                hid = hashlib.sha256(f"{extra}|{researcher}|llm".encode()).hexdigest()[:12]
                out.append(
                    Hypothesis(
                        id=hid,
                        statement=extra,
                        rationale="LLM-proposed extension",
                        researcher=researcher,
                        created_at=now,
                    )
                )
        return out

    # ── 3. explain results ──────────────────────────────────────────────────────

    def explain_results(self, report: ValidationReport) -> str:
        """Plain-English narration of a ValidationReport for a human."""
        decay = _decay(report.is_sharpe, report.oos_sharpe)
        sig = "passes" if report.adjusted_pvalue < self._criteria.significance_alpha else "fails"
        lines = [
            f"Verdict: {report.verdict.value.upper()}.",
            f"In-sample Sharpe {report.is_sharpe:.2f} decayed "
            f"{decay:.0%} out-of-sample to {report.oos_sharpe:.2f} "
            f"(OOS return {report.oos_return:.1%}, max drawdown "
            f"{report.oos_max_drawdown:.1%}, {report.oos_trades} trades).",
            f"Data-mining-adjusted p-value {report.adjusted_pvalue:.3f} over "
            f"{report.n_trials} trial(s) "
            f"({sig} the {self._criteria.significance_alpha:.0%} bar).",
        ]
        if report.reasons:
            lines.append("Guards: " + "; ".join(report.reasons) + ".")
        text = " ".join(lines)
        if self._llm is not None:
            text += "\n\n" + self._llm(f"Explain to a portfolio manager, plainly:\n{text}")
        return text

    # ── 4. review strategy code ─────────────────────────────────────────────────

    def review_code(self, source: str) -> CodeReview:
        """Static scan for common quant look-ahead / leakage / reproducibility bugs."""
        findings: list[CodeFinding] = []
        for lineno, line in enumerate(source.splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            for pattern, severity, issue, fix in _CODE_RULES:
                if pattern.search(line):
                    findings.append(CodeFinding(lineno, severity, issue, fix))
        findings.sort(key=lambda f: ({"high": 0, "medium": 1, "low": 2}[f.severity], f.line))
        llm_notes = ""
        if self._llm is not None:
            llm_notes = self._llm(
                "Review this strategy code for look-ahead bias and overfitting. "
                f"List concrete risks only:\n\n{source[:6000]}"
            )
        return CodeReview(findings, llm_notes)

    # ── 5. detect possible biases ───────────────────────────────────────────────

    def detect_biases(
        self,
        report: ValidationReport,
        oos_observations: int | None = None,
        code_review: CodeReview | None = None,
    ) -> BiasReport:
        """Flag statistical biases from a report + optional context. Reuses the
        same thresholds the Phase-6 verdict uses, so 'assistant says overfit' and
        'framework rejected for fragility' never disagree."""
        c = self._criteria
        cv = report.param_cv
        n_obs = oos_observations if oos_observations is not None else report.oos_trades
        flags = {
            "overfitting": cv is not None and cv > c.max_param_cv,
            "data_mining": report.n_trials > 1 and report.adjusted_pvalue >= c.significance_alpha,
            "small_sample": n_obs < c.min_oos_observations,
            "look_ahead": bool(code_review and code_review.has_lookahead),
        }
        notes: list[str] = []
        if flags["overfitting"]:
            notes.append(
                f"Parameter CV {cv:.2f} > {c.max_param_cv}: performance swings wildly "
                "across the grid — likely fit to noise."
            )
        if flags["data_mining"]:
            notes.append(
                f"{report.n_trials} trials, adjusted p={report.adjusted_pvalue:.3f}: "
                "edge does not survive the multiple-testing haircut."
            )
        if flags["small_sample"]:
            notes.append(
                f"Only {n_obs} OOS observations (< {c.min_oos_observations}): the Sharpe "
                "estimate has a huge standard error — treat as inconclusive."
            )
        if flags["look_ahead"]:
            notes.append("Code review found look-ahead — OOS results may be fiction.")
        # survivorship/selection can't be read off the numbers: always caution.
        notes.append(
            "Reminder (not auto-detectable): confirm the universe is survivorship-bias "
            "free and the sample period wasn't cherry-picked."
        )
        return BiasReport(flags, notes)

    # ── 6. create research report ───────────────────────────────────────────────

    def write_report(
        self,
        record: ExperimentRecord,
        oos_observations: int | None = None,
        code_review: CodeReview | None = None,
    ) -> str:
        """Assemble a Markdown research report from an experiment record."""
        r = record.report
        biases = self.detect_biases(r, oos_observations, code_review)
        verdict_icon = {Verdict.ACCEPT: "✅", Verdict.REJECT: "❌", Verdict.INCONCLUSIVE: "❓"}[
            r.verdict
        ]
        md = [
            f"# Research Report — {record.strategy_name} v{record.strategy_version}",
            f"**Experiment:** `{record.id}`  |  **Researcher:** {record.researcher}  "
            f"|  **Date:** {record.created_at:%Y-%m-%d}",
            f"**Dataset:** `{record.dataset_version}`  |  "
            f"**Features:** {', '.join(record.features_used) or 'n/a'}",
            "",
            f"## Verdict: {verdict_icon} {r.verdict.value.upper()}",
            self.explain_results(r),
            "",
            "## Parameters",
            "".join(f"- `{k}` = {v}\n" for k, v in record.params.items()) or "- (none)\n",
            "## Bias & Robustness",
        ]
        md += [
            f"- {'⚠️' if v else '✔️'} **{k}**: {'flagged' if v else 'clear'}"
            for k, v in biases.flags.items()
        ]
        md += [""] + [f"> {n}" for n in biases.notes]
        if code_review and code_review.findings:
            md += ["", "## Code Review"]
            md += [
                f"- L{f.line} [{f.severity}] {f.issue} — *fix:* {f.fix}"
                for f in code_review.findings
            ]
        md += [
            "",
            "---",
            "*Generated by the AI Research Assistant. Advisory only — a human "
            "researcher owns the accept/deploy decision. The assistant cannot trade.*",
        ]
        return "\n".join(md)

    # ── internals ────────────────────────────────────────────────────────────────

    @staticmethod
    def _section(text: str, name: str) -> str:
        """Grab a named section's body up to the next heading or blank block."""
        m = re.search(rf"(?im)^\s*{name}\s*[:.\n]", text)
        if not m:
            return ""
        rest = text[m.end() :]
        # stop at the next ALL-CAPS/Title heading line or a blank line following prose
        stop = re.search(r"\n\s*\n|\n\s*(?:[A-Z][a-z]+\s*){0,3}\n", rest)
        return " ".join(rest[: stop.start() if stop else 400].split())

    @staticmethod
    def _extract_claims(text: str) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
        claims = [
            s for s in sentences if any(m in s.lower() for m in _CLAIM_MARKERS) and len(s) < 300
        ]
        return list(dict.fromkeys(claims))  # dedupe, preserve order

    @staticmethod
    def _keywords(text: str, k: int = 8) -> list[str]:
        words = re.findall(r"[a-z]{4,}", text.lower())
        counts = Counter(w for w in words if w not in _STOPWORDS)
        return [w for w, _ in counts.most_common(k)]

    @staticmethod
    def _as_testable(claim: str) -> str:
        c = claim.strip().rstrip(".")
        return f"Test whether {c[0].lower() + c[1:]}" if c else "Test the paper's claim"


def _decay(is_sharpe: float, oos_sharpe: float) -> float:
    if is_sharpe <= 0:
        return 0.0
    return min(1.0, max(0.0, 1.0 - oos_sharpe / is_sharpe))
