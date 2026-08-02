"""
SQLite Mobile Database Exporter for English Dataset System Engine.
Optimizes, indexes, vacuums, and verifies english_dataset.db for mobile app integration.
"""

import time
import sqlite3
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, List

from config.settings import EXPORT_SQLITE_PATH, OUTPUT_DIR

logger = logging.getLogger(__name__)


class SQLiteExporter:
    """Exports and optimizes the SQLite database for mobile offline consumption."""

    def __init__(self, db_path: Path = EXPORT_SQLITE_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def optimize_and_package(self) -> Dict[str, Any]:
        """
        Applies PRAGMAs, creates missing indexes, runs ANALYZE and VACUUM.
        Returns metadata about the packaged database file.
        """
        if not self.db_path.exists():
            raise FileNotFoundError(f"Export database not found at {self.db_path}")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # 1. Ensure foreign keys enabled
        cursor.execute("PRAGMA foreign_keys = ON;")

        # 2. Build or verify indexes
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_words_lemma ON words(lemma);")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sentences_text_en ON sentences(text_en);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reflex_cefr_type ON reflex_drills(drill_type, sentence_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_nodes_tree_parent ON dialogue_nodes(tree_id, parent_node_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrases_cefr ON phrases(cefr_level);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrases_type ON phrases(phrase_type);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrase_sentences_phrase ON phrase_sentences(phrase_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrase_sentences_sentence ON phrase_sentences(sentence_id);")

        # 3. Analyze query planner statistics
        cursor.execute("ANALYZE;")

        # 4. Set production WAL PRAGMAs
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")

        conn.commit()

        # 5. Vacuum to minimize size
        cursor.execute("VACUUM;")
        conn.close()

        size_bytes = self.db_path.stat().st_size
        size_mb = round(size_bytes / (1024 * 1024), 2)

        logger.info("Database successfully packaged and optimized at %s (%s MB)", self.db_path, size_mb)
        return {
            "path": str(self.db_path),
            "size_bytes": size_bytes,
            "size_mb": size_mb
        }

    def verify_foreign_keys(self) -> List[Tuple]:
        """
        Runs PRAGMA foreign_key_check to ensure zero orphan records.
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA foreign_key_check;")
        violations = cursor.fetchall()
        conn.close()
        return violations

    def benchmark_reflex_query_speed(self, iterations: int = 50) -> float:
        """
        Benchmarks average query speed in milliseconds for random distractor drills.
        Target: < 5ms.
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        query = """
            SELECT r.id, r.prompt_text, r.correct_answer, r.distractors_json, s.cefr_level
            FROM reflex_drills r
            JOIN sentences s ON r.sentence_id = s.id
            WHERE r.drill_type = 'speed_translation'
            ORDER BY r.id LIMIT 1;
        """

        durations = []
        for _ in range(iterations):
            start = time.perf_counter()
            cursor.execute(query)
            cursor.fetchone()
            end = time.perf_counter()
            durations.append((end - start) * 1000.0)

        conn.close()
        avg_ms = round(sum(durations) / len(durations), 3) if durations else 0.0
        logger.info("Average reflex query execution time: %s ms over %d runs", avg_ms, iterations)
        return avg_ms
