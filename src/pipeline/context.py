"""Shared pipeline context — passed to every stage."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any
import logging

from config.settings import (
    EXPORT_SQLITE_PATH, PROCESSED_DATA_DIR, OUTPUT_DIR,
    RAW_DATA_DIR, AUDIO_DIR, KAIKKI_JSON_PATH,
    TATOEBA_SENTENCES_PATH, TATOEBA_LINKS_PATH,
    SUBTLEX_FREQ_PATH, NGSL_PATH,
    OPENSUBTITLES_EN, OPENSUBTITLES_VI,
    ENVICORPORA_TED_LIKE_EN, ENVICORPORA_TED_LIKE_VI,
    ENVICORPORA_BASIC_EN, ENVICORPORA_BASIC_VI,
    STAGING_DUCKDB_PATH, SENTENCE_LINK_CHECKPOINT,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """Immutable config + mutable state shared across all pipeline stages."""

    sqlite_path: Path = EXPORT_SQLITE_PATH
    duckdb_path: Path = STAGING_DUCKDB_PATH
    processed_dir: Path = PROCESSED_DATA_DIR
    output_dir: Path = OUTPUT_DIR
    raw_dir: Path = RAW_DATA_DIR
    audio_dir: Path = AUDIO_DIR
    checkpoint_dir: Path = PROCESSED_DATA_DIR

    force_reset: bool = False
    vi_budget: int = 1000
    audio_limit: int = 5000

    duckdb_conn: Any = None
    sqlite_conn: Any = None
    lemma_cache: Optional[Dict[str, int]] = None
    stats: Dict[str, Any] = field(default_factory=dict)

    def checkpoint_path(self, stage_name: str) -> Path:
        return self.checkpoint_dir / f"checkpoint_{stage_name}.json"
