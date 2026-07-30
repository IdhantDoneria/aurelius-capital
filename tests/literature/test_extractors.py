"""Offline tests for extractor parsers (no HTTP calls)."""

from datetime import UTC, datetime

import pytest

from aurelius.literature.extractors.arxiv import ArxivExtractor
from aurelius.literature.extractors.crossref import CrossRefExtractor
from aurelius.literature.extractors.nber import NBERExtractor

# ── Fixtures ──────────────────────────────────────────────────────────────────

_ARXIV_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2301.12345v2</id>
    <title>Momentum and Mean Reversion  in Equities</title>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
    <summary>We document momentum in equity returns over 1963-2020.</summary>
    <published>2023-01-15T00:00:00Z</published>
  </entry>
</feed>"""

_NBER_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <item>
      <title>Factor Investing at Scale</title>
      <link>https://www.nber.org/papers/w99999</link>
      <description>&lt;p&gt;Factor portfolios generate alpha.&lt;/p&gt;</description>
      <pubDate>Mon, 15 Jan 2024 00:00:00 +0000</pubDate>
      <dc:creator>Jane Doe</dc:creator>
    </item>
  </channel>
</rss>"""

_CROSSREF_ITEM = {
    "DOI": "10.1111/jofi.12345",
    "title": ["Volatility Risk Premium"],
    "author": [{"given": "John", "family": "Smith"}, {"given": "Mary", "family": "Lee"}],
    "published-print": {"date-parts": [[2023, 6, 1]]},
    "abstract": "<jats:p>We study the <jats:bold>volatility</jats:bold> risk premium.</jats:p>",
    "URL": "https://doi.org/10.1111/jofi.12345",
}

# ── arXiv ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_arxiv_parse_count():
    papers = ArxivExtractor()._parse(_ARXIV_ATOM)
    assert len(papers) == 1


@pytest.mark.unit
def test_arxiv_source_and_id():
    p = ArxivExtractor()._parse(_ARXIV_ATOM)[0]
    assert p.source == "arxiv"
    assert p.source_id == "2301.12345"


@pytest.mark.unit
def test_arxiv_strips_version_from_id():
    p = ArxivExtractor()._parse(_ARXIV_ATOM)[0]
    assert "v2" not in p.source_id
    assert "v" not in p.source_id


@pytest.mark.unit
def test_arxiv_title_normalized():
    p = ArxivExtractor()._parse(_ARXIV_ATOM)[0]
    assert "\n" not in p.title
    assert "Momentum and Mean Reversion" in p.title


@pytest.mark.unit
def test_arxiv_authors():
    p = ArxivExtractor()._parse(_ARXIV_ATOM)[0]
    assert p.authors == ["Alice Smith", "Bob Jones"]


@pytest.mark.unit
def test_arxiv_published_at():
    p = ArxivExtractor()._parse(_ARXIV_ATOM)[0]
    assert p.published_at is not None
    assert p.published_at.year == 2023
    assert p.published_at.month == 1


@pytest.mark.unit
def test_arxiv_url_format():
    p = ArxivExtractor()._parse(_ARXIV_ATOM)[0]
    assert p.url == "https://arxiv.org/abs/2301.12345"


# ── NBER ──────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_nber_parse_count():
    papers = NBERExtractor()._parse(_NBER_RSS, limit=10)
    assert len(papers) == 1


@pytest.mark.unit
def test_nber_source_and_handle():
    p = NBERExtractor()._parse(_NBER_RSS, limit=10)[0]
    assert p.source == "nber"
    assert p.source_id == "w99999"


@pytest.mark.unit
def test_nber_abstract_strips_html():
    p = NBERExtractor()._parse(_NBER_RSS, limit=10)[0]
    assert "<p>" not in p.abstract
    assert "Factor portfolios" in p.abstract


@pytest.mark.unit
def test_nber_author():
    p = NBERExtractor()._parse(_NBER_RSS, limit=10)[0]
    assert p.authors == ["Jane Doe"]


@pytest.mark.unit
def test_nber_published_at():
    p = NBERExtractor()._parse(_NBER_RSS, limit=10)[0]
    assert p.published_at is not None
    assert p.published_at.year == 2024


# ── CrossRef ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_crossref_parse_item():
    now = datetime.now(UTC)
    p = CrossRefExtractor("jf")._item_to_paper(_CROSSREF_ITEM, now)
    assert p.source == "jf"
    assert p.source_id == "10.1111/jofi.12345"
    assert p.title == "Volatility Risk Premium"
    assert p.authors == ["John Smith", "Mary Lee"]


@pytest.mark.unit
def test_crossref_strips_jats_tags():
    now = datetime.now(UTC)
    p = CrossRefExtractor("jf")._item_to_paper(_CROSSREF_ITEM, now)
    assert "<jats:" not in p.abstract
    assert "volatility" in p.abstract.lower()


@pytest.mark.unit
def test_crossref_date_full():
    p = CrossRefExtractor("jf")._item_to_paper(_CROSSREF_ITEM, datetime.now(UTC))
    assert p.published_at is not None
    assert p.published_at.year == 2023
    assert p.published_at.month == 6


@pytest.mark.unit
def test_crossref_date_year_only():
    d = CrossRefExtractor._parse_date({"date-parts": [[2024]]})
    assert d is not None
    assert d.year == 2024
    assert d.month == 1
    assert d.day == 1


@pytest.mark.unit
def test_crossref_date_year_month():
    d = CrossRefExtractor._parse_date({"date-parts": [[2024, 3]]})
    assert d is not None
    assert d.month == 3
    assert d.day == 1


@pytest.mark.unit
def test_crossref_date_none():
    assert CrossRefExtractor._parse_date(None) is None
    assert CrossRefExtractor._parse_date({}) is None


@pytest.mark.unit
def test_crossref_rejects_unknown_source():
    with pytest.raises(ValueError, match="Unknown CrossRef source"):
        CrossRefExtractor("unknown")


@pytest.mark.unit
def test_crossref_ssrn_source():
    ext = CrossRefExtractor("ssrn")
    assert ext.source == "ssrn"
