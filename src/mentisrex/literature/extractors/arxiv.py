"""arXiv q-fin.* extractor via the public Atom API (no auth required)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime

import httpx

from mentisrex.core.logging import get_logger
from mentisrex.literature.extractors.base import SourceExtractor
from mentisrex.literature.models import Paper, paper_id

logger = get_logger(__name__)

_URL = "https://export.arxiv.org/api/query"
_CATEGORIES = (
    "cat:q-fin.PM OR cat:q-fin.TR OR cat:q-fin.ST OR cat:q-fin.RM "
    "OR cat:q-fin.MF OR cat:q-fin.GN OR cat:q-fin.CP OR cat:q-fin.EC"
)
_ATOM = "http://www.w3.org/2005/Atom"


class ArxivExtractor(SourceExtractor):
    source = "arxiv"

    def fetch(self, limit: int = 100, since: date | None = None) -> list[Paper]:
        resp = httpx.get(
            _URL,
            params={
                "search_query": _CATEGORIES,
                "start": 0,
                "max_results": limit,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            },
            timeout=30,
        )
        resp.raise_for_status()
        papers = self._parse(resp.text)
        if since:
            papers = [p for p in papers if p.published_at and p.published_at >= since]
        logger.info("arxiv_fetch", fetched=len(papers))
        return papers

    def _parse(self, xml_text: str) -> list[Paper]:
        root = ET.fromstring(xml_text)
        now = datetime.now(UTC)
        papers = []
        for entry in root.findall(f"{{{_ATOM}}}entry"):
            try:
                papers.append(self._entry_to_paper(entry, now))
            except Exception as exc:
                logger.warning("arxiv_parse_skip", error=str(exc))
        return papers

    def _entry_to_paper(self, entry: ET.Element, now: datetime) -> Paper:
        def _t(tag: str) -> str:
            el = entry.find(f"{{{_ATOM}}}{tag}")
            return el.text.strip() if el is not None and el.text else ""

        raw_id = _t("id")  # http://arxiv.org/abs/2301.00001v1
        source_id = raw_id.split("/abs/")[-1].split("v")[0]  # 2301.00001

        authors = [
            n.text.strip()
            for a in entry.findall(f"{{{_ATOM}}}author")
            if (n := a.find(f"{{{_ATOM}}}name")) is not None and n.text
        ]

        published_str = _t("published")
        published_at: date | None = None
        if published_str:
            try:
                published_at = datetime.fromisoformat(published_str.replace("Z", "+00:00")).date()
            except ValueError:
                pass

        return Paper(
            id=paper_id("arxiv", source_id),
            source="arxiv",
            source_id=source_id,
            title=_t("title").replace("\n", " ").strip(),
            authors=authors,
            published_at=published_at,
            abstract=_t("summary").replace("\n", " ").strip(),
            url=f"https://arxiv.org/abs/{source_id}",
            ingested_at=now,
        )
