from __future__ import annotations

import argparse

from .clean import clean_item, deduplicate
from .sources import collect_all
from .storage import DEFAULT_DB_PATH, VectorStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect, clean, deduplicate and index mining intelligence data.")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days.")
    parser.add_argument("--limit-per-source", type=int, default=200, help="Minimum target rows per source type.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite vector store path.")
    parser.add_argument("--no-synthetic", action="store_true", help="Disable synthetic backfill for development.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raw_items = collect_all(
        days=args.days,
        limit_per_source_type=args.limit_per_source,
        fill_synthetic=not args.no_synthetic,
    )
    cleaned = [doc for item in raw_items if (doc := clean_item(item)) is not None]
    documents = deduplicate(cleaned)
    store = VectorStore(args.db)
    inserted = store.upsert_many(documents)
    print(f"raw_items={len(raw_items)} cleaned={len(cleaned)} unique={len(documents)} upserted={inserted} total={store.count()}")


if __name__ == "__main__":
    main()
