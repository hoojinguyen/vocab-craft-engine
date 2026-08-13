import argparse
from typing import List, Optional

def parse_arguments(args_list: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description="Vocab Craft Engine Pipeline Runner")
    parser.add_argument("--steps", type=str, help="Comma-separated step names to execute (e.g. schema_init,phrase_mwe).")
    parser.add_argument("--skip-steps", type=str, help="Comma-separated step names to skip.")
    parser.add_argument("--dry-run", action="store_true", help="Preview step execution plan without modifying database.")
    parser.add_argument("--force-reset", action="store_true", help="Force complete database reset and re-ingest everything.")
    parser.add_argument("--skip-dict", action="store_true", help="Skip Kaikki dictionary ingestion step.")
    parser.add_argument("--vi-budget", type=int, default=1000, help="Max MT translation attempts for Vietnamese backfill.")
    parser.add_argument("--build-core-pack", action="store_true", help="Build the curated Core 3000 word pack.")
    return parser.parse_args(args_list)
