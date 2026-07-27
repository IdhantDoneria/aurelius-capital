"""NBER working papers extractor via RSS feed (no auth required)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime

import httpx

from aurelius.core.logging import get_logger
from aurelius.literature.extractors.base import SourceExtractor
from aurelius.literature.models import Paper, paper_id

logger = get_logger(__name__)

_RSS = "https://www.nber.org/feeds/new_nber_papers.xml"
_DC = "http://purl.org/dc/elements/1.1/"
_TAGS_RE = re.compile(r"<[^>]+>")


class NBERExtractor(SourceExtractor):
    source = "nber"

    def fetch(self, limit: int = 100, since: date | None = None) -> list[Paper]:
        resp = httpx.get(_RSS, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        papers = self._parse(resp.text, limit)
        if since:
            papers = [p for p in papers if p.published_at and p.published_at >= since]
        logger.info("nber_fetch", fetched=len(papers))
        return papers

    def _parse(self, xml_text: str, limit: int) -> list[Paper]:
        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return []
        now = datetime.now(UTC)
        papers = []
        for item in channel.findall("item")[:limit]:
            try:
                papers.append(self._item_to_paper(item, now))
            except Exception as exc:
                logger.warning("nber_parse_skip", error=str(exc))
        return papers

    def _item_to_paper(self, item: ET.Element, now: datetime) -> Paper:
        def _t(tag: str) -> str:
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        link = _t("link")
        handle = link.rstrip("/").split("/")[-1]  # e.g. "w32100"

        published_at: date | None = None
        pub_date_str = _t("pubDate")
        if pub_date_str:
            try:
                published_at = parsedate_to_datetime(pub_date_str).date()
            except Exception:
                pass

        creators = [
            el.text.strip()
            for el in item.findall(f"{{{_DC}}}creator")
            if el.text
        ]

        abstract = _TAGS_RE.sub("", _t("description")).strip()

        return Paper(
            id=paper_id("nber", handle),
            source="nber",
            source_id=handle,
            title=_t("title"),
            authors=creators,
            published_at=published_at,
            abstract=abstract,
            url=link,
            ingested_at=now,
        )
