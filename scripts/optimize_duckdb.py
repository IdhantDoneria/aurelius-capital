"""Optimize all DuckDB files: VACUUM + export every table to ZSTD-compressed Parquet.

For each .duckdb file found under --root:
  1. Skips files with an active .wal (in-use / locked) — warns instead of crashing.
  2. VACUUMs the file to reclaim deleted-row space and compact the storage.
  3. Exports every user table to ZSTD Parquet under data/parquet/{db_stem}/{table}.parquet
  4. Verifies exported row count == DuckDB row count before marking success.
  5. Prints a size report: DuckDB size vs Parquet size, space saved.

Parquet is typically 4–10x smaller than DuckDB for financial time-series due to
columnar compression. The DuckDB files are left in place (the system still needs
them). Delete them manually once you've confirmed Parquet covers what you need.

Usage:
    .venv/bin/python scripts/optimize_duckdb.py
    .venv/bin/python scripts/optimize_duckdb.py --root /path/to/mentisrex-capital
    .venv/bin/python scripts/optimize_duckdb.py --vacuum-only
    .venv/bin/python scripts/optimize_duckdb.py --export-only
    .venv/bin/python scripts/optimize_duckdb.py --dry-run
    .venv/bin/python scripts/optimize_duckdb.py --db data/fundamentals.duckdb  # single file
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb

_PARQUET_ROOT = Path("data/parquet")
_ROW_GROUP_SIZE = 122_880  # 128K rows — good balance of compression and random access


def _mb(path: Path) -> float:
    return path.stat().st_size / 1_048_576


def _fmt(mb: float) -> str:
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.1f} MB"


def _user_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_type = 'BASE TABLE' "
        "ORDER BY table_name"
    ).fetchall()
    return [r[0] for r in rows]


def vacuum_db(db_path: Path, *, dry_run: bool) -> float:
    """VACUUM the DuckDB file. Returns size after (MB)."""
    before = _mb(db_path)
    if dry_run:
        print(f"    [dry-run] VACUUM {db_path.name}")
        return before
    con = duckdb.connect(str(db_path))
    try:
        con.execute("VACUUM")
        con.execute("CHECKPOINT")
    finally:
        con.close()
    after = _mb(db_path)
    saved = before - after
    if saved > 0.1:
        print(f"    VACUUM: {_fmt(before)} → {_fmt(after)} (saved {_fmt(saved)})")
    else:
        print(f"    VACUUM: {_fmt(after)} (no significant compaction)")
    return after


def export_db(db_path: Path, parquet_dir: Path, *, dry_run: bool) -> dict[str, int]:
    """Export all user tables to ZSTD Parquet. Returns {table: row_count}."""
    parquet_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, int] = {}

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        tables = _user_tables(con)
        if not tables:
            print("    (no user tables)")
            return results

        for table in tables:
            out = parquet_dir / f"{table}.parquet"
            row_count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # type: ignore[index]

            if dry_run:
                print(f"    [dry-run] EXPORT {table} ({row_count:,} rows) → {out}")
                results[table] = row_count
                continue

            if row_count == 0:
                print(f"    {table}: empty, skipping export")
                results[table] = 0
                continue

            t0 = time.time()
            con.execute(
                f"COPY (SELECT * FROM {table}) TO '{out}' "
                f"(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE {_ROW_GROUP_SIZE})"
            )
            elapsed = time.time() - t0

            # Verify row count
            verify = duckdb.execute(f"SELECT COUNT(*) FROM read_parquet('{out}')").fetchone()[0]  # type: ignore[index]
            if verify != row_count:
                print(f"    !! {table}: MISMATCH db={row_count:,} parquet={verify:,} — keeping file for inspection")
            else:
                parquet_mb = _mb(out)
                print(f"    {table}: {row_count:,} rows → {_fmt(parquet_mb)} ({elapsed:.1f}s)")
            results[table] = verify
    finally:
        con.close()

    return results


def process(db_path: Path, *, parquet_root: Path, vacuum: bool, export: bool, dry_run: bool) -> tuple[float, float]:
    """Process one DuckDB file. Returns (db_size_mb, parquet_total_mb)."""
    db_mb = _mb(db_path)
    wal = db_path.with_suffix(".duckdb.wal")
    if not wal.exists():
        wal = Path(str(db_path) + ".wal")

    print(f"\n{'[dry-run] ' if dry_run else ''}▶ {db_path.name}  ({_fmt(db_mb)})")

    if wal.exists():
        print(f"  !! .wal file present — DB may be in use. Skipping VACUUM, exporting read-only.")
        vacuum = False

    if vacuum:
        db_mb = vacuum_db(db_path, dry_run=dry_run)

    parquet_mb = 0.0
    if export:
        stem = db_path.stem
        parquet_dir = parquet_root / stem
        results = export_db(db_path, parquet_dir, dry_run=dry_run)
        if not dry_run and results:
            parquet_mb = sum(
                _mb(parquet_dir / f"{t}.parquet")
                for t in results
                if results[t] > 0 and (parquet_dir / f"{t}.parquet").exists()
            )
            if parquet_mb > 0:
                ratio = db_mb / parquet_mb
                print(f"  Parquet total: {_fmt(parquet_mb)} (compression ratio {ratio:.1f}x)")

    return db_mb, parquet_mb


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=".", help="project root (default: cwd)")
    p.add_argument("--db", default=None, help="process a single .duckdb file instead of scanning")
    p.add_argument("--parquet-root", default=str(_PARQUET_ROOT))
    p.add_argument("--vacuum-only", action="store_true")
    p.add_argument("--export-only", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="show what would be done, no writes")
    args = p.parse_args()

    do_vacuum = not args.export_only
    do_export = not args.vacuum_only
    parquet_root = Path(args.parquet_root)

    if args.db:
        db_files = [Path(args.db)]
    else:
        root = Path(args.root)
        db_files = sorted(
            p for p in root.rglob("*.duckdb")
            if ".venv" not in p.parts and "__pycache__" not in p.parts
        )

    if not db_files:
        print("No .duckdb files found.")
        sys.exit(0)

    print(f"Found {len(db_files)} DuckDB file(s). vacuum={do_vacuum} export={do_export}")

    total_db_mb = 0.0
    total_parquet_mb = 0.0
    failed: list[str] = []

    for db_path in db_files:
        try:
            db_mb, parquet_mb = process(db_path, parquet_root=parquet_root, vacuum=do_vacuum, export=do_export, dry_run=args.dry_run)
            total_db_mb += db_mb
            total_parquet_mb += parquet_mb
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {exc}")
            failed.append(db_path.name)

    print(f"\n{'=' * 60}")
    print(f"Total DuckDB on disk : {_fmt(total_db_mb)}")
    if do_export and not args.dry_run and total_parquet_mb > 0:
        savings = total_db_mb - total_parquet_mb
        ratio = total_db_mb / total_parquet_mb if total_parquet_mb else 0
        print(f"Total Parquet size   : {_fmt(total_parquet_mb)}")
        print(f"Parquet compression  : {ratio:.1f}x")
        print(f"Space saveable*      : {_fmt(savings)}")
        print(f"  * if you delete the .duckdb files after verifying Parquet is complete")
        print(f"  Parquet location   : {parquet_root.resolve()}")
    if failed:
        print(f"\nFailed ({len(failed)}): {', '.join(failed)}")
    print("Done.")


if __name__ == "__main__":
    main()
