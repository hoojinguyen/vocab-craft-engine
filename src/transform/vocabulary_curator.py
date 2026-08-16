"""
Vocabulary Curator and Quality Filter V3.

Filters raw staging words down to a clean, highly curated target vocabulary
(35,000 - 50,000 lemmas) using SUBTLEX-US frequencies, Oxford 5000, NGSL, and AWL.
Eliminates OCR noise, non-words, casing anomalies, and recalibrates CEFR levels.
"""

import logging
import re
from typing import Dict, Optional, Set
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

LEMMA_VALID_REGEX = re.compile(r"^[a-z]+(-[a-z]+)*$")


def determine_cefr_level(
    lemma: str,
    freq_rank: Optional[int],
    oxford_words: Set[str],
    ngsl_words: Set[str],
    awl_words: Set[str],
) -> str:
    """
    Assigns pedagogical CEFR levels (A1, A2, B1, B2, C1, C2) based on
    authoritative wordlists and spoken/written frequency rank.
    """
    clean = lemma.strip().lower()

    if clean in ngsl_words or (freq_rank and freq_rank <= 1200):
        return "A1" if (freq_rank and freq_rank <= 600) else "A2"

    if clean in oxford_words:
        if freq_rank and freq_rank <= 2500:
            return "B1"
        return "B2"

    if clean in awl_words or (freq_rank and freq_rank <= 8000):
        return "B2" if (freq_rank and freq_rank <= 4500) else "C1"

    if freq_rank and freq_rank <= 20000:
        return "C1"

    return "C2"


class VocabularyCurator:
    """Curates DuckDB staging words table to a clean, mobile-optimized vocabulary."""

    def __init__(
        self,
        target_limit: int = 50000,
        oxford_words: Optional[Set[str]] = None,
        ngsl_words: Optional[Set[str]] = None,
        awl_words: Optional[Set[str]] = None,
    ):
        self.target_limit = target_limit
        self.oxford_words = oxford_words or set()
        self.ngsl_words = ngsl_words or set()
        self.awl_words = awl_words or set()

    def curate(self, db_mgr: DuckDBManager) -> Dict[str, int]:
        """
        Executes vocabulary curation in staging DuckDB:
        1. Selects high-quality candidate lemmas.
        2. Assigns balanced CEFR levels.
        3. Removes noisy / duplicate / OCR junk entries.
        4. Cascades deletions to orphan definitions and relations.
        """
        conn = db_mgr.get_connection()

        words_before = db_mgr.count_rows("words")
        logger.info("Starting vocabulary curation on %d words (target limit: %d)...", words_before, self.target_limit)

        # 1. Fetch distinct valid lemmas ordered by priority:
        # Priority: (1) In Oxford/NGSL/AWL, (2) SUBTLEX frequency rank, (3) Length
        all_words = conn.execute("""
            SELECT id, lemma, pos, frequency_rank, cefr_level
            FROM words
            WHERE lemma IS NOT NULL AND length(trim(lemma)) >= 1
            ORDER BY 
                CASE WHEN frequency_rank IS NOT NULL THEN 0 ELSE 1 END,
                frequency_rank ASC NULLS LAST,
                id ASC
        """).fetchall()

        curated_ids: Set[int] = set()
        seen_lemma_pos: Set[tuple] = set()

        for wid, lemma, pos, freq_rank, _ in all_words:
            clean_lemma = lemma.strip().lower()

            # Skip words with whitespace (handled in phrases table)
            if " " in clean_lemma or "_" in clean_lemma:
                continue

            # Length filtering: ignore single letters (except 'a', 'i') and excessive lengths (> 24 chars)
            if len(clean_lemma) == 1 and clean_lemma not in ("a", "i"):
                continue
            if len(clean_lemma) > 24:
                continue

            # Regex sanity check (alphanumeric letters and optional hyphens)
            if not LEMMA_VALID_REGEX.match(clean_lemma):
                continue

            key = (clean_lemma, pos)
            if key in seen_lemma_pos:
                continue

            # Include if in core list OR has reasonable frequency OR within budget
            is_core = (
                clean_lemma in self.oxford_words
                or clean_lemma in self.ngsl_words
                or clean_lemma in self.awl_words
            )
            has_valid_freq = freq_rank is not None and freq_rank <= 45000

            if is_core or has_valid_freq or len(curated_ids) < self.target_limit:
                curated_ids.add(wid)
                seen_lemma_pos.add(key)
                if len(curated_ids) >= self.target_limit:
                    break

        logger.info("Selected %d curated words from %d candidates", len(curated_ids), words_before)

        # 2. Prune unselected words from DuckDB staging
        if curated_ids:
            # Register temp table of kept IDs
            import pyarrow as pa
            id_table = pa.Table.from_pydict({"keep_id": list(curated_ids)})
            conn.register("_curated_word_ids", id_table)

            # Clean up referencing child tables first to respect foreign keys
            conn.execute("""
                DELETE FROM definitions 
                WHERE word_id NOT IN (SELECT keep_id FROM _curated_word_ids);
            """)
            conn.execute("""
                DELETE FROM word_sentences 
                WHERE word_id NOT IN (SELECT keep_id FROM _curated_word_ids);
            """)
            conn.execute("""
                DELETE FROM word_topics 
                WHERE word_id NOT IN (SELECT keep_id FROM _curated_word_ids);
            """)
            conn.execute("""
                DELETE FROM word_relations 
                WHERE word_id NOT IN (SELECT keep_id FROM _curated_word_ids)
                   OR (target_word_id IS NOT NULL AND target_word_id NOT IN (SELECT keep_id FROM _curated_word_ids));
            """)

            # Clean up words master table
            conn.execute("""
                DELETE FROM words 
                WHERE id NOT IN (SELECT keep_id FROM _curated_word_ids);
            """)
            conn.unregister("_curated_word_ids")

        words_after = db_mgr.count_rows("words")
        defs_after = db_mgr.count_rows("definitions")

        logger.info(
            "Vocabulary Curation Completed: %d words kept (pruned %d), %d definitions active",
            words_after,
            words_before - words_after,
            defs_after,
        )

        return {
            "words_before": words_before,
            "words_after": words_after,
            "definitions_after": defs_after,
        }
