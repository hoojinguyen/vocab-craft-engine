import argparse
from typing import List, Optional

from config.settings import (
    KAIKKI_JSON_PATH,
    TATOEBA_SENTENCES_PATH,
    TATOEBA_LINKS_PATH,
    SUBTLEX_FREQ_PATH,
    NGSL_PATH,
    OPENSUBTITLES_EN,
    OPENSUBTITLES_VI,
    ENVICORPORA_TED_LIKE_EN,
    ENVICORPORA_TED_LIKE_VI,
    ENVICORPORA_BASIC_EN,
    ENVICORPORA_BASIC_VI,
)

REQUIRED_RAW_FILES = [
    KAIKKI_JSON_PATH,
    TATOEBA_SENTENCES_PATH,
    TATOEBA_LINKS_PATH,
    SUBTLEX_FREQ_PATH,
    NGSL_PATH,
    OPENSUBTITLES_EN,
    OPENSUBTITLES_VI,
    ENVICORPORA_TED_LIKE_EN,
    ENVICORPORA_TED_LIKE_VI,
    ENVICORPORA_BASIC_EN,
    ENVICORPORA_BASIC_VI,
]


def get_missing_raw_files(paths) -> list:
    """Returns the subset of raw files that are missing or empty (0 bytes)."""
    return [p for p in paths if not p.exists() or p.stat().st_size == 0]


def parse_arguments(args_list: Optional[List[str]] = None):
    parser = argparse.ArgumentParser(description="Vocab Craft Engine Pipeline Runner")
    parser.add_argument("--steps", type=str, help="Comma-separated step names to execute (e.g. schema_init,phrase_mwe).")
    parser.add_argument("--skip-steps", type=str, help="Comma-separated step names to skip.")
    parser.add_argument("--dry-run", action="store_true", help="Preview step execution plan without modifying database.")
    parser.add_argument("--force-reset", action="store_true", help="Force complete database reset and re-ingest everything.")
    parser.add_argument("--skip-dict", action="store_true", help="Skip Kaikki dictionary ingestion step.")
    parser.add_argument("--vi-budget", type=int, default=1000, help="Max MT translation attempts for Vietnamese backfill.")
    parser.add_argument("--build-core-pack", action="store_true", help="Build the curated Core 3000 word pack.")
    parser.add_argument("--resume", action="store_true", help="Resume execution from previous failed state.")
    parser.add_argument("--no-tui", action="store_false", dest="tui", default=True, help="Disable Rich Terminal UI dashboard.")
    parser.add_argument("--max-retries", type=int, default=3, help="Maximum auto-retries per step (default: 3).")
    parser.add_argument("--log-dir", type=str, default="logs", help="Directory to store file logs and JSON reports.")
    return parser.parse_args(args_list)
