"""CrossRef extractor for JF, JFE, RFS, QF journals and SSRN preprints.

CrossRef is the registration agency for DOIs. All four journals deposit metadata
there; SSRN papers use DOI prefix 10.2139.

Rate limit: CrossRef allows ~50 req/s for polite pool (with User-Agent email).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

import httpx

from mentisrex.core.logging import get_logger
from mentisrex.literature.extractors.base import SourceExtractor
from mentisrex.literature.models import Paper, paper_id

logger = get_logger(__name__)

_ISSNS: dict[str, str] = {
    "jf": "0022-1082",  # Journal of Finance
    "jfe": "0304-405X",  # Journal of Financial Economics
    "rfs": "0893-9454",  # Review of Financial Studies
    "qf": "1469-7688",  # Quantitative Finance
}
_SSRN_PREFIX = "10.2139"
_TAGS_RE = re.compile(r"<[^>]+>")
_UA = "mentisrex-capital/0.1 (research; mailto:research@mentisrex.internal)"

_ALL_SOURCES = {*_ISSNS, "ssrn"}


class CrossRefExtractor(SourceExtractor):
    def __init__(self, source: str) -> None:
        if source not in _ALL_SOURCES:
            raise ValueError(f"Unknown CrossRef source '{source}'. Valid: {sorted(_ALL_SOURCES)}")
        self.source = source

    def fetch(self, limit: int = 100, since: date | None = None) -> list[Paper]:
        if self.source in _ISSNS:
            url = f"https://api.crossref.org/journals/{_ISSNS[self.source]}/works"
        else:
            url = f"https://api.crossref.org/prefixes/{_SSRN_PREFIX}/works"

        params: dict[str, str] = {
            "rows": limit,  # type: ignore
            "sort": "published",
            "order": "desc",
            "select": "DOI,title,author,published-print,published-online,abstract,URL",
        }
        if since:
            params["filter"] = f"from-pub-date:{since.isoformat()}"

        resp = httpx.get(url, params=params, timeout=30, headers={"User-Agent": _UA})
        resp.raise_for_status()
        items = resp.json().get("message", {}).get("items", [])

        now = datetime.now(UTC)
        papers = []
        for item in items:
            try:
                papers.append(self._item_to_paper(item, now))
            except Exception as exc:
                logger.warning("crossref_parse_skip", source=self.source, error=str(exc))

        logger.info("crossref_fetch", source=self.source, fetched=len(papers))
        return papers

    def _item_to_paper(self, item: dict, now: datetime) -> Paper:
        doi = item.get("DOI", "")
        titles = item.get("title", [])
        title = titles[0] if titles else ""

        authors = [
            f"{a.get('given', '')} {a.get('family', '')}".strip() for a in item.get("author", [])
        ]

        published_at = self._parse_date(item.get("published-print") or item.get("published-online"))

        abstract = _TAGS_RE.sub("", item.get("abstract", "")).strip()
        url = item.get("URL") or f"https://doi.org/{doi}"

        return Paper(
            id=paper_id(self.source, doi),
            source=self.source,
            source_id=doi,
            title=title,
            authors=authors,
            published_at=published_at,
            abstract=abstract,
            url=url,
            ingested_at=now,
        )

    @staticmethod
    def _parse_date(date_obj: dict | None) -> date | None:
        if not date_obj:
            return None
        parts = date_obj.get("date-parts", [[]])
        if not parts or not parts[0]:
            return None
        p = parts[0]
        try:
            return date(p[0], p[1] if len(p) > 1 else 1, p[2] if len(p) > 2 else 1)
        except (ValueError, IndexError):
            return None
