#!/usr/bin/env python
"""Literature ingestion CLI.

Fetches papers from one or more sources, optionally enriches them via LLM,
and stores results in data/literature.duckdb.

Usage:
  python scripts/ingest_literature.py --source arxiv --limit 100
  python scripts/ingest_literature.py --source all --since 2024-01-01
  python scripts/ingest_literature.py --source jf jfe rfs qf --limit 50 --enrich
  python scripts/ingest_literature.py --stats
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mentisrex.literature.extractors import SOURCES, get_extractor
from mentisrex.literature.store import LiteratureStore


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest quant literature into DuckDB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--source", nargs="+", choices=[*SOURCES, "all"], default=["arxiv"],
        metavar="SOURCE", help=f"Source(s) to ingest. Choices: {SOURCES} or all",
    )
    parser.add_argument("--limit", type=int, default=100, help="Papers per source")
    parser.add_argument("--since", type=date.fromisoformat, default=None,
                        metavar="YYYY-MM-DD", help="Only papers published after this date")
    parser.add_argument("--db", default="./data/literature.duckdb",
                        help="Path to DuckDB file (default: ./data/literature.duckdb)")
    parser.add_argument("--enrich", action="store_true",
                        help="Run LLM enrichment (requires ANTHROPIC_API_KEY env var)")
    parser.add_argument("--stats", action="store_true",
                        help="Print DB stats and exit")
    args = parser.parse_args()

    store = LiteratureStore(args.db)

    if args.stats:
        _print_stats(store)
        return

    sources = SOURCES if "all" in args.source else args.source
    llm = _build_llm() if args.enrich else None

    total_new = 0
    for src in sources:
        extractor = get_extractor(src)
        try:
            papers = extractor.fetch(limit=args.limit, since=args.since)
        except Exception as exc:
            print(f"[{src}] FETCH FAILED: {exc}", file=sys.stderr)
            continue

        new = 0
        for paper in papers:
            if store.exists(paper.source, paper.source_id):
                continue  # skip existing — preserves enrichment data
            if llm:
                from mentisrex.literature.enrichment import enrich
                paper = enrich(paper, llm)
            store.upsert(paper)
            new += 1

        print(f"[{src:6s}] fetched={len(papers):3d}  new={new:3d}")
        total_new += new

    print(f"\nDone. {total_new} new paper(s) ingested.")
    _print_stats(store)


def _print_stats(store: LiteratureStore) -> None:
    s = store.stats()
    print(f"\nDB stats: total={s['total']}  enriched={s['enriched']}")
    for src, cnt in sorted(s["by_source"].items()):
        print(f"  {src:6s}: {cnt}")


def _build_llm():
    """Build LLM callable from ANTHROPIC_API_KEY. Falls back to raw httpx if sdk absent."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: --enrich requires ANTHROPIC_API_KEY env var", file=sys.stderr)
        sys.exit(1)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        def llm_sdk(prompt: str) -> str:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text  # type: ignore[index]

        return llm_sdk
    except ImportError:
        pass

    # Fallback: httpx direct call (anthropic sdk not installed)
    import httpx

    def llm_http(prompt: str) -> str:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    return llm_http


if __name__ == "__main__":
    main()
