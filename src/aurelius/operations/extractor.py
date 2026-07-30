"""Extract structured metadata from research papers (PDF, text, markdown, JSON)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

from aurelius.core.logging import get_logger
from aurelius.operations.models import PermanentIngestError

logger = get_logger(__name__)

_HAS_PYPDF = importlib.util.find_spec("pypdf") is not None

# Common section headers used in academic papers
_SECTION_PATTERNS = {
    "abstract": re.compile(r"(?i)\babstract\b[:\s]*(.{100,2000}?)(?=\n\n|\Z|\bintroduction\b|\b1\b\.?\s)", re.DOTALL),
    "introduction": re.compile(r"(?i)\bintroduction\b[:\s]*(.{100,3000}?)(?=\n\n[A-Z0-9]|\Z)", re.DOTALL),
    "methodology": re.compile(r"(?i)\b(?:methodology|methods|approach)\b[:\s]*(.{100,3000}?)(?=\n\n[A-Z0-9]|\Z)", re.DOTALL),
    "results": re.compile(r"(?i)\b(?:results|findings|empirical results)\b[:\s]*(.{100,3000}?)(?=\n\n[A-Z0-9]|\Z)", re.DOTALL),
    "conclusion": re.compile(r"(?i)\b(?:conclusion|conclusions|summary)\b[:\s]*(.{100,2000}?)(?=\n\n[A-Z0-9]|\Z|\breferences\b)", re.DOTALL),
}

_YEAR_PATTERN = re.compile(r"\b(19[89]\d|20[0-3]\d)\b")
_DOI_PATTERN = re.compile(r"\b10\.\d{4,}/\S+")
_ARXIV_PATTERN = re.compile(r"arXiv[:\s]+(\d{4}\.\d{4,5})", re.IGNORECASE)
_DATASET_KEYWORDS = [
    "CRSP", "Compustat", "Bloomberg", "FactSet", "Quandl", "Ken French",
    "S&P 500", "Russell", "MSCI", "Fama-French", "TAQ", "TRACE",
    "Yahoo Finance", "WRDS", "Refinitiv", "Datastream",
]
_FEATURE_KEYWORDS = [
    "momentum", "value", "size", "quality", "profitability", "volatility",
    "beta", "book-to-market", "earnings yield", "price-to-earnings",
    "return reversal", "idiosyncratic", "factor", "signal", "alpha",
    "Sharpe", "drawdown", "turnover", "liquidity", "sentiment",
]
_STAT_KEYWORDS = [
    "t-statistic", "p-value", "Sharpe ratio", "alpha", "beta", "R-squared",
    "regression", "OLS", "panel", "bootstrap", "cross-validation", "Fama-MacBeth",
]


def compute_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_text(path: Path) -> str:
    """Extract raw text from PDF, text, markdown, or JSON file."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".json":
        return _extract_json(path)
    # .txt, .md, .rst, .tex and anything else — read as text
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("text_read_failed", path=str(path), error=str(exc))
        return ""


def extract_metadata(path: Path, raw_text: str) -> dict[str, Any]:
    """Parse raw text into structured paper metadata."""
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    meta: dict[str, Any] = {
        "title": _extract_title(path, lines),
        "authors": _extract_authors(lines),
        "year": _extract_year(raw_text),
        "doi": _extract_doi(raw_text),
        "arxiv_id": _extract_arxiv(raw_text),
        "abstract": _extract_section("abstract", raw_text),
        "methodology": _extract_section("methodology", raw_text),
        "results": _extract_section("results", raw_text),
        "conclusion": _extract_section("conclusion", raw_text),
        "datasets_mentioned": _extract_datasets(raw_text),
        "features_mentioned": _extract_features(raw_text),
        "statistical_tests": _extract_stats(raw_text),
        "reference_count": _count_references(raw_text),
        "word_count": len(raw_text.split()),
        "source_file": path.name,
    }
    return meta


def _extract_pdf(path: Path) -> str:
    if not _HAS_PYPDF:
        logger.warning("pypdf_not_installed", path=str(path))
        return f"[PDF: {path.name} — install pypdf for text extraction]"
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages)
    except Exception as exc:
        logger.warning("pdf_extraction_failed", path=str(path), error=str(exc))
        raise PermanentIngestError(f"Corrupt or unreadable PDF: {exc}") from exc


def _extract_json(path: Path) -> str:
    try:
        data = json.loads(path.read_text())
        # If it's already structured metadata, convert to text for uniform processing
        if isinstance(data, dict):
            return "\n".join(f"{k}: {v}" for k, v in data.items() if v)
        return str(data)
    except Exception:
        return path.read_text(errors="replace")


def _extract_title(path: Path, lines: list[str]) -> str:
    # First non-trivial line is often the title in academic PDFs
    for line in lines[:5]:
        if len(line) > 10 and not line.startswith("arXiv") and not re.match(r"^\d", line):
            return line[:200]
    return path.stem.replace("-", " ").replace("_", " ")


def _extract_authors(lines: list[str]) -> list[str]:
    # Authors are usually on lines 2-5, contain commas or "and", no periods ending sentences
    candidates = []
    for line in lines[1:8]:
        if "," in line or " and " in line.lower():
            if not any(kw in line.lower() for kw in ("abstract", "university", "journal", "doi")):
                parts = re.split(r",|\band\b", line, flags=re.IGNORECASE)
                candidates = [p.strip() for p in parts if 3 < len(p.strip()) < 60]
                if candidates:
                    break
    return candidates[:10]


def _extract_year(text: str) -> int | None:
    matches = _YEAR_PATTERN.findall(text[:2000])
    if matches:
        return int(max(matches))
    return None


def _extract_doi(text: str) -> str:
    m = _DOI_PATTERN.search(text[:3000])
    return m.group(0).rstrip(".,)") if m else ""


def _extract_arxiv(text: str) -> str:
    m = _ARXIV_PATTERN.search(text[:2000])
    return m.group(1) if m else ""


def _extract_section(name: str, text: str) -> str:
    m = _SECTION_PATTERNS[name].search(text)
    if m:
        return m.group(1).strip()[:1500]
    return ""


def _extract_datasets(text: str) -> list[str]:
    return [kw for kw in _DATASET_KEYWORDS if re.search(rf"\b{re.escape(kw)}\b", text, re.IGNORECASE)]


def _extract_features(text: str) -> list[str]:
    return [kw for kw in _FEATURE_KEYWORDS if re.search(rf"\b{re.escape(kw)}\b", text, re.IGNORECASE)]


def _extract_stats(text: str) -> list[str]:
    return [kw for kw in _STAT_KEYWORDS if re.search(rf"\b{re.escape(kw)}\b", text, re.IGNORECASE)]


def _count_references(text: str) -> int:
    # Rough heuristic: count [N] style or author-year style references
    bracket_refs = len(re.findall(r"\[\d+\]", text))
    authoryear_refs = len(re.findall(r"\([A-Z][a-z]+(?:\s+et\s+al\.)?,?\s+\d{4}\)", text))
    return max(bracket_refs, authoryear_refs)
