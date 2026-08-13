#!/usr/bin/env python
"""Hypothesis generation CLI.

Reads enriched papers from LiteratureStore, generates structured hypotheses,
runs quality and deduplication checks, stores results in HypothesisStore.

Usage:
  python scripts/generate_hypotheses.py --from-papers --source arxiv --limit 50
  python scripts/generate_hypotheses.py --from-paper <paper_id>
  python scripts/generate_hypotheses.py --list --status Draft
  python scripts/generate_hypotheses.py --list --category factor_anomaly
  python scripts/generate_hypotheses.py --stats
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mentisrex.hypothesis.deduplication import DuplicateStatus, check_duplicates
from mentisrex.hypothesis.generator import generate
from mentisrex.hypothesis.quality import check_quality
from mentisrex.hypothesis.store import HypothesisStore
from mentisrex.literature.store import LiteratureStore


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate hypotheses from literature",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd")

    gen = sub.add_parser("generate", help="Generate hypotheses from enriched papers")
    gen.add_argument("--source", nargs="+", default=None,
                     metavar="SOURCE", help="Filter by literature source")
    gen.add_argument("--limit", type=int, default=50, help="Max papers to process")
    gen.add_argument("--paper", default=None, metavar="PAPER_ID",
                     help="Generate from a single paper ID")
    gen.add_argument("--researcher", default="llm")
    gen.add_argument("--lit-db", default="./data/literature.duckdb")
    gen.add_argument("--hyp-db", default="./data/hypothesis.duckdb")

    lst = sub.add_parser("list", help="List hypotheses from the repository")
    lst.add_argument("--status", default=None,
                     choices=["Draft", "Active", "Rejected", "Promoted"])
    lst.add_argument("--category", default=None)
    lst.add_argument("--query", default=None)
    lst.add_argument("--limit", type=int, default=20)
    lst.add_argument("--hyp-db", default="./data/hypothesis.duckdb")

    stats_p = sub.add_parser("stats", help="Print repository stats")
    stats_p.add_argument("--hyp-db", default="./data/hypothesis.duckdb")

    # Default to stats if no subcommand given
    args = parser.parse_args()
    if args.cmd is None:
        parser.print_help()
        return

    if args.cmd == "generate":
        _cmd_generate(args)
    elif args.cmd == "list":
        _cmd_list(args)
    elif args.cmd == "stats":
        _cmd_stats(args)


def _cmd_generate(args) -> None:
    lit_store = LiteratureStore(args.lit_db)
    hyp_store = HypothesisStore(args.hyp_db)
    llm = _build_llm()

    if args.paper:
        paper = lit_store.get(args.paper)
        if paper is None:
            print(f"Paper {args.paper} not found in literature store.", file=sys.stderr)
            sys.exit(1)
        papers = [paper]
    else:
        papers = lit_store.search(
            source=args.source[0] if args.source and len(args.source) == 1 else None,
            enriched_only=True,
            limit=args.limit,
        )
        if args.source and len(args.source) > 1:
            papers = [p for p in papers if p.source in args.source]

    if not papers:
        print("No enriched papers found. Run ingest_literature.py --enrich first.")
        return

    existing = hyp_store.all_statements()
    total_inserted = total_rejected = total_near_dup = 0

    for paper in papers:
        candidates = generate(paper, llm=llm, researcher=args.researcher)

        for h in candidates:
            qr = check_quality(h)
            if not qr.passed:
                h.status = "Rejected"
                h.rejection_reason = "; ".join(qr.reasons)
                hyp_store.insert(h)
                total_rejected += 1
                continue

            dr = check_duplicates(h, existing)
            if dr.status == DuplicateStatus.DUPLICATE:
                h.status = "Rejected"
                h.rejection_reason = f"duplicate of {dr.similar_ids[0]}"
                hyp_store.insert(h)
                total_rejected += 1
                continue
            if dr.status == DuplicateStatus.NEAR_DUPLICATE:
                h.similar_to = dr.similar_ids
                total_near_dup += 1

            if hyp_store.insert(h):
                existing.append((h.id, h.testable_statement))
                total_inserted += 1

        print(
            f"[{paper.source:6s}] {paper.title[:60]!r} → {len(candidates)} candidate(s)"
        )

    print(
        f"\nDone. inserted={total_inserted}  rejected={total_rejected}  "
        f"near_duplicate_flagged={total_near_dup}"
    )


def _cmd_list(args) -> None:
    hyp_store = HypothesisStore(args.hyp_db)
    results = hyp_store.search(
        query=args.query,
        status=args.status,
        category=args.category,
        limit=args.limit,
    )
    if not results:
        print("No hypotheses found.")
        return
    for h in results:
        print(f"[{h.status:8s}] [{h.research_category or '?':25s}] {h.testable_statement[:80]}")
        print(f"           id={h.id}  v{h.version}  {h.generation_method}  papers={h.parent_papers}")
        print()


def _cmd_stats(args) -> None:
    hyp_store = HypothesisStore(args.hyp_db)
    s = hyp_store.stats()
    print(f"Total hypotheses: {s['total']}")
    print("\nBy status:")
    for k, v in sorted(s["by_status"].items()):
        print(f"  {k:12s}: {v}")
    print("\nBy category (non-rejected):")
    for k, v in sorted(s["by_category"].items(), key=lambda x: -x[1]):
        print(f"  {k:30s}: {v}")
    print("\nBy generation method:")
    for k, v in sorted(s["by_method"].items()):
        print(f"  {k:10s}: {v}")


def _build_llm():
    """Build LLM callable from ANTHROPIC_API_KEY. Returns None if key absent."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "Note: ANTHROPIC_API_KEY not set — using template fallback (lower quality).",
            file=sys.stderr,
        )
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        def llm_sdk(prompt: str) -> str:
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text  # type: ignore[index]

        return llm_sdk
    except ImportError:
        pass

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
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]

    return llm_http


if __name__ == "__main__":
    main()
