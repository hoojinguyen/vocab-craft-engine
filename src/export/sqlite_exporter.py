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


POS_MAP = {"other": 0, "noun": 1, "verb": 2, "adj": 3, "adv": 4, "pronoun": 5, "prep": 6, "conj": 7, "interj": 8, "phrase": 9}
POS_REV_MAP = {v: k for k, v in POS_MAP.items()}

CEFR_MAP = {"Unknown": 0, "A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}
CEFR_REV_MAP = {v: k for k, v in CEFR_MAP.items()}

DRILL_MAP = {"speed_translation": 1, "cloze_reflex": 2, "listening_speed": 3}
RELATION_MAP = {"synonym": 1, "antonym": 2, "hypernym": 3, "hyponym": 4}


class SQLiteExporter:
    """Exports and optimizes the SQLite database for mobile offline consumption."""

    def __init__(self, db_path: Path = EXPORT_SQLITE_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (table_name,))
        return cursor.fetchone() is not None

    def _migrate_table_enums(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        enum_cols: Dict[str, Dict[str, int]]
    ):
        """
        Recreates table with TINYINT column affinity for enum columns and maps text values to ints.
        """
        if not self._table_exists(conn, table_name):
            return

        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info('{table_name}');")
        cols = cursor.fetchall()

        needs_migration = False
        for col in cols:
            name, ctype = col[1], col[2]
            if name in enum_cols and "TINYINT" not in ctype.upper() and "INT" not in ctype.upper():
                needs_migration = True
                break

        if not needs_migration:
            for col_name, mapping in enum_cols.items():
                cases = " ".join(f"WHEN '{k}' THEN {v}" for k, v in mapping.items())
                cursor.execute(f"""
                    UPDATE {table_name}
                    SET {col_name} = CASE {col_name} {cases} ELSE 0 END
                    WHERE {col_name} IS NOT NULL AND typeof({col_name}) != 'integer';
                """)
            return

        pk_cols = [c for c in cols if c[5] > 0]
        pk_cols.sort(key=lambda c: c[5])
        is_composite_pk = len(pk_cols) > 1

        col_defs = []
        col_names = []
        select_exprs = []

        for cid, name, ctype, notnull, dflt_val, pk in cols:
            col_names.append(name)
            notnull_sql = " NOT NULL" if notnull else ""
            dflt_sql = f" DEFAULT {dflt_val}" if dflt_val is not None else ""
            pk_sql = ""
            if pk and not is_composite_pk:
                pk_sql = " PRIMARY KEY AUTOINCREMENT" if "AUTOINCREMENT" in ctype.upper() else " PRIMARY KEY"

            if name in enum_cols:
                mapping = enum_cols[name]
                cases = " ".join(f"WHEN '{k}' THEN {v}" for k, v in mapping.items())
                int_cases = " ".join(f"WHEN {v} THEN {v}" for v in mapping.values())
                col_defs.append(f"{name} TINYINT{notnull_sql}{dflt_sql}{pk_sql}")
                select_exprs.append(f"CASE {name} {cases} {int_cases} ELSE 0 END")
            else:
                col_defs.append(f"{name} {ctype}{notnull_sql}{dflt_sql}{pk_sql}")
                select_exprs.append(name)

        if is_composite_pk:
            pk_names = [c[1] for c in pk_cols]
            col_defs.append(f"PRIMARY KEY ({', '.join(pk_names)})")

        cursor.execute("PRAGMA foreign_keys = OFF;")
        cursor.execute(f"CREATE TABLE {table_name}_new ({', '.join(col_defs)});")
        cursor.execute(f"INSERT INTO {table_name}_new ({', '.join(col_names)}) SELECT {', '.join(select_exprs)} FROM {table_name};")
        cursor.execute(f"DROP TABLE {table_name};")
        cursor.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name};")
        cursor.execute("PRAGMA foreign_keys = ON;")

    def _migrate_schema_and_enums(self, conn: sqlite3.Connection):
        """
        Migrates text columns for enums (pos, cefr_level, drill_type, relation_type)
        to TINYINT integer codes, and creates SQL views for backward compatibility.
        """
        self._migrate_table_enums(conn, "words", {"pos": POS_MAP, "cefr_level": CEFR_MAP})
        self._migrate_table_enums(conn, "reflex_drills", {"drill_type": DRILL_MAP})
        self._migrate_table_enums(conn, "word_relations", {"relation_type": RELATION_MAP})
        self._migrate_table_enums(conn, "sentences", {"cefr_level": CEFR_MAP})

        cursor = conn.cursor()
        if self._table_exists(conn, "words"):
            cursor.execute("PRAGMA table_info(words);")
            columns = [row[1] for row in cursor.fetchall()]
            select_parts = []
            for col in columns:
                if col == "pos":
                    select_parts.append("""CASE pos 
                        WHEN 1 THEN 'noun' WHEN 2 THEN 'verb' WHEN 3 THEN 'adj' WHEN 4 THEN 'adv'
                        WHEN 5 THEN 'pronoun' WHEN 6 THEN 'prep' WHEN 7 THEN 'conj' WHEN 8 THEN 'interj'
                        WHEN 9 THEN 'phrase' ELSE 'other' END AS pos""")
                elif col == "cefr_level":
                    select_parts.append("""CASE cefr_level 
                        WHEN 1 THEN 'A1' WHEN 2 THEN 'A2' WHEN 3 THEN 'B1'
                        WHEN 4 THEN 'B2' WHEN 5 THEN 'C1' WHEN 6 THEN 'C2' ELSE 'Unknown' END AS cefr_level""")
                else:
                    select_parts.append(col)
            select_clause = ", ".join(select_parts)
            cursor.execute("DROP VIEW IF EXISTS v_words;")
            cursor.execute(f"CREATE VIEW v_words AS SELECT {select_clause} FROM words;")

        conn.commit()

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

        # 2. Migrate enums and create views
        self._migrate_schema_and_enums(conn)

        # 3. Build or verify indexes safely
        indexes = [
            ("words", "CREATE UNIQUE INDEX IF NOT EXISTS idx_words_lemma ON words(lemma);"),
            ("sentences", "CREATE UNIQUE INDEX IF NOT EXISTS idx_sentences_text_en ON sentences(text_en);"),
            ("reflex_drills", "CREATE INDEX IF NOT EXISTS idx_reflex_cefr_type ON reflex_drills(drill_type, sentence_id);"),
            ("dialogue_nodes", "CREATE INDEX IF NOT EXISTS idx_nodes_tree_parent ON dialogue_nodes(tree_id, parent_node_id);"),
            ("phrases", "CREATE INDEX IF NOT EXISTS idx_phrases_cefr ON phrases(cefr_level);"),
            ("phrases", "CREATE INDEX IF NOT EXISTS idx_phrases_type ON phrases(phrase_type);"),
            ("phrase_sentences", "CREATE INDEX IF NOT EXISTS idx_phrase_sentences_phrase ON phrase_sentences(phrase_id);"),
            ("phrase_sentences", "CREATE INDEX IF NOT EXISTS idx_phrase_sentences_sentence ON phrase_sentences(sentence_id);"),
            ("word_relations", "CREATE UNIQUE INDEX IF NOT EXISTS idx_word_relations_unique ON word_relations(word_id, relation_type, target_text);"),
            ("word_relations", "CREATE INDEX IF NOT EXISTS idx_word_relations_target ON word_relations(target_word_id);"),
            ("word_topics", "CREATE UNIQUE INDEX IF NOT EXISTS idx_word_topics_unique ON word_topics(word_id, topic);"),
            ("word_topics", "CREATE INDEX IF NOT EXISTS idx_word_topics_topic ON word_topics(topic);"),
            ("definitions", "CREATE INDEX IF NOT EXISTS idx_definitions_word_id ON definitions(word_id);"),
        ]
        for tbl, sql in indexes:
            if self._table_exists(conn, tbl):
                cursor.execute(sql)

        # 4. Analyze query planner statistics
        cursor.execute("ANALYZE;")
        conn.commit()

        # 5. Vacuum to minimize size
        cursor.execute("VACUUM;")

        # 6. Set production WAL PRAGMAs
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")

        conn.commit()
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
            WHERE r.drill_type = 1 OR r.drill_type = 'speed_translation'
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

