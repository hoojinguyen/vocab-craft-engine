"""SUBTLEX-US Frequency Ranking & CEFR Level Ingestor."""

import logging
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class FrequencyIngestor:
    def populate_frequency_ranks(self, db_mgr: DuckDBManager, subtlex_path: Path) -> int:
        if not subtlex_path.exists():
            logger.warning("SUBTLEX frequency file not found at %s", subtlex_path)
            return 0

        conn = db_mgr.get_connection()

        # Step 1: Create temporary staging table for SUBTLEX frequency data
        conn.execute("DROP TABLE IF EXISTS _tmp_subtlex;")
        conn.execute(f"""
            CREATE TEMP TABLE _tmp_subtlex AS 
            SELECT lower(trim(Word)) AS word, TRY_CAST(rank AS INTEGER) AS rank 
            FROM read_csv_auto('{subtlex_path}', header=True)
            WHERE rank IS NOT NULL;
        """)

        # Step 2: Update words.frequency_rank by joining on lemma
        conn.execute("""
            UPDATE words
            SET frequency_rank = _tmp_subtlex.rank
            FROM _tmp_subtlex
            WHERE words.lemma = _tmp_subtlex.word;
        """)

        # Step 3: Compute CEFR level for all words based on standard rank thresholds
        conn.execute("""
            UPDATE words
            SET cefr_level = CASE
                WHEN frequency_rank IS NOT NULL AND frequency_rank <= 500 THEN 'A1'
                WHEN frequency_rank IS NOT NULL AND frequency_rank <= 1500 THEN 'A2'
                WHEN frequency_rank IS NOT NULL AND frequency_rank <= 3500 THEN 'B1'
                WHEN frequency_rank IS NOT NULL AND frequency_rank <= 7000 THEN 'B2'
                WHEN frequency_rank IS NOT NULL AND frequency_rank <= 15000 THEN 'C1'
                ELSE 'C2'
            END;
        """)

        # Count how many words have frequency rank assigned
        res = conn.execute("SELECT count(*) FROM words WHERE frequency_rank IS NOT NULL").fetchone()
        updated_count = res[0] if res else 0

        conn.execute("DROP TABLE IF EXISTS _tmp_subtlex;")
        logger.info("Populated frequency rank for %d words and computed CEFR levels", updated_count)
        return updated_count
