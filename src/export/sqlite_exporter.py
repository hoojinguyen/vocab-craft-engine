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
        enum_cols: Dict[str, Dict[str, int]] = None,
        without_rowid: bool = False,
    ):
        """
        Recreates table with TINYINT column affinity for enum columns and maps text values to ints.
        Dynamically retrieves all columns from PRAGMA table_info(table_name) to avoid column truncation.
        Preserves original column names, types, constraints, and optionally applies WITHOUT ROWID.
        """
        if not self._table_exists(conn, table_name):
            return

        cursor = conn.cursor()
        enum_cols = enum_cols or {}

        cursor.execute(f"PRAGMA table_info('{table_name}');")
        cols = cursor.fetchall()
        if not cols:
            return

        needs_migration = without_rowid
        if not needs_migration:
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

        default_junction_pks = {
            "word_topics": ["word_id", "topic"],
            "word_relations": ["word_id", "relation_type", "target_text"],
            "phrase_sentences": ["phrase_id", "sentence_id"],
            "pattern_sentences": ["pattern_id", "sentence_id"],
        }
        col_by_name = {c[1]: c for c in cols}

        composite_pk_names = []
        if is_composite_pk:
            composite_pk_names = [c[1] for c in pk_cols]
        elif (len(pk_cols) == 0 or without_rowid) and table_name in default_junction_pks:
            needed = default_junction_pks[table_name]
            if all(k in col_by_name for k in needed):
                composite_pk_names = needed

        col_defs = []
        col_names = []
        select_exprs = []

        for cid, name, ctype, notnull, dflt_val, pk in cols:
            col_names.append(name)
            notnull_sql = " NOT NULL" if notnull else ""
            dflt_sql = f" DEFAULT {dflt_val}" if dflt_val is not None else ""
            pk_sql = ""
            if pk and not is_composite_pk and not composite_pk_names:
                if without_rowid:
                    pk_sql = " PRIMARY KEY"
                else:
                    pk_sql = " PRIMARY KEY AUTOINCREMENT" if "AUTOINCREMENT" in ctype.upper() or (pk and name.lower() == "id" and "INT" in ctype.upper()) else " PRIMARY KEY"

            unique_sql = ""
            if name.lower() == "lemma":
                unique_sql = " UNIQUE"

            if name in enum_cols:
                mapping = enum_cols[name]
                cases = " ".join(f"WHEN '{k}' THEN {v}" for k, v in mapping.items())
                int_cases = " ".join(f"WHEN {v} THEN {v}" for v in mapping.values())
                col_defs.append(f"{name} TINYINT{notnull_sql}{unique_sql}{dflt_sql}{pk_sql}")
                select_exprs.append(f"CASE {name} {cases} {int_cases} ELSE 0 END")
            else:
                col_defs.append(f"{name} {ctype}{notnull_sql}{unique_sql}{dflt_sql}{pk_sql}")
                select_exprs.append(name)

        if composite_pk_names:
            col_defs.append(f"PRIMARY KEY ({', '.join(composite_pk_names)})")

        has_pk = (len(pk_cols) > 0) or bool(composite_pk_names)
        without_rowid_sql = " WITHOUT ROWID" if (without_rowid and has_pk) else ""
        cursor.execute(f"CREATE TABLE {table_name}_new ({', '.join(col_defs)}){without_rowid_sql};")
        cursor.execute(f"INSERT OR IGNORE INTO {table_name}_new ({', '.join(col_names)}) SELECT {', '.join(select_exprs)} FROM {table_name};")
        cursor.execute(f"DROP TABLE {table_name};")
        cursor.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name};")

        if "lemma" in col_names:
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_words_lemma ON words(lemma);")

    def _migrate_schema_and_enums(self, conn: sqlite3.Connection):
        """
        Migrates text columns for enums (pos, cefr_level, drill_type, relation_type)
        to TINYINT integer codes, recreates tables with explicit schema constraints and
        WITHOUT ROWID link tables, and creates SQL views for backward compatibility.
        Wrapped in a transaction for database consistency.
        """
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = OFF;")
        conn.commit()

        try:
            conn.execute("BEGIN TRANSACTION;")

            # 1. Recreate words table dynamically with TINYINT enums & UNIQUE lemma
            self._migrate_table_enums(conn, "words", {"pos": POS_MAP, "cefr_level": CEFR_MAP})

            # 2. Recreate junction link tables as WITHOUT ROWID
            self._migrate_table_enums(conn, "word_topics", without_rowid=True)
            self._migrate_table_enums(conn, "word_relations", {"relation_type": RELATION_MAP}, without_rowid=True)
            self._migrate_table_enums(conn, "phrase_sentences", without_rowid=True)
            self._migrate_table_enums(conn, "pattern_sentences", without_rowid=True)

            # 3. Other enum tables migration
            self._migrate_table_enums(conn, "reflex_drills", {"drill_type": DRILL_MAP})
            self._migrate_table_enums(conn, "sentences", {"cefr_level": CEFR_MAP})

            # 4. Create backward compatibility view for words
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
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.execute("PRAGMA foreign_keys = ON;")
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
            ("words", "CREATE UNIQUE INDEX IF NOT EXISTS idx_words_lemma_cov ON words(lemma, id, pos, cefr_level, frequency_rank, ipa_uk, ipa_us);"),
            ("sentences", "CREATE UNIQUE INDEX IF NOT EXISTS idx_sentences_text_en ON sentences(text_en);"),
            ("reflex_drills", "CREATE INDEX IF NOT EXISTS idx_reflex_cefr_type ON reflex_drills(drill_type, sentence_id);"),
            ("reflex_drills", "CREATE INDEX IF NOT EXISTS idx_reflex_cov ON reflex_drills(drill_type, id, sentence_id, prompt_text);"),
            ("dialogue_nodes", "CREATE INDEX IF NOT EXISTS idx_nodes_tree_parent ON dialogue_nodes(tree_id, parent_node_id);"),
            ("phrases", "CREATE INDEX IF NOT EXISTS idx_phrases_cefr ON phrases(cefr_level);"),
            ("phrases", "CREATE INDEX IF NOT EXISTS idx_phrases_type ON phrases(phrase_type);"),
            ("phrase_sentences", "CREATE INDEX IF NOT EXISTS idx_phrase_sentences_phrase ON phrase_sentences(phrase_id);"),
            ("phrase_sentences", "CREATE INDEX IF NOT EXISTS idx_phrase_sentences_sentence ON phrase_sentences(sentence_id);"),
            ("pattern_sentences", "CREATE INDEX IF NOT EXISTS idx_pattern_sentences_pid ON pattern_sentences(pattern_id, sentence_id);"),
            ("word_relations", "CREATE UNIQUE INDEX IF NOT EXISTS idx_word_relations_unique ON word_relations(word_id, relation_type, target_text);"),
            ("word_relations", "CREATE INDEX IF NOT EXISTS idx_word_relations_target ON word_relations(target_word_id);"),
            ("word_topics", "CREATE UNIQUE INDEX IF NOT EXISTS idx_word_topics_unique ON word_topics(word_id, topic);"),
            ("word_topics", "CREATE INDEX IF NOT EXISTS idx_word_topics_topic ON word_topics(topic);"),
            ("definitions", "CREATE INDEX IF NOT EXISTS idx_definitions_word_id ON definitions(word_id);"),
        ]
        for tbl, sql in indexes:
            if self._table_exists(conn, tbl):
                try:
                    cursor.execute(sql)
                except sqlite3.OperationalError as e:
                    logger.warning("Skipping index creation for %s (%s): %s", tbl, sql, e)

        # Build FTS5 external content table for words
        if self._table_exists(conn, "words"):
            cursor.execute("DROP TABLE IF EXISTS words_fts;")
            cursor.execute("""
                CREATE VIRTUAL TABLE words_fts USING fts5(
                    lemma,
                    content='words',
                    content_rowid='id',
                    tokenize='porter ascii'
                );
            """)
            cursor.execute("INSERT INTO words_fts(words_fts) VALUES('rebuild');")


        # 4. Analyze query planner statistics
        cursor.execute("ANALYZE;")
        conn.commit()

        # 5. Set page_size and Vacuum to minimize size
        cursor.execute("PRAGMA page_size = 4096;")
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

    def benchmark_all_queries(self, iterations: int = 100) -> Dict[str, float]:
        """
        Runs automated SLA performance benchmarks for core query workloads.
        Target: < 5.0 ms per query type.
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        results = {}

        # 1. Exact Lemma Lookup
        q_lemma = "SELECT id, lemma, pos, cefr_level, ipa_uk FROM words WHERE lemma = 'apple';"
        durations = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            cursor.execute(q_lemma)
            cursor.fetchone()
            durations.append((time.perf_counter() - t0) * 1000.0)
        results["lemma_lookup_ms"] = round(sum(durations) / len(durations), 3) if durations else 0.0

        # 2. FTS5 Search
        if self._table_exists(conn, "words_fts"):
            q_fts = "SELECT w.id, w.lemma, w.pos FROM words_fts f JOIN words w ON f.rowid = w.id WHERE words_fts MATCH 'appl*' LIMIT 20;"
            durations = []
            for _ in range(iterations):
                t0 = time.perf_counter()
                cursor.execute(q_fts)
                cursor.fetchall()
                durations.append((time.perf_counter() - t0) * 1000.0)
            results["fts_search_ms"] = round(sum(durations) / len(durations), 3) if durations else 0.0

        # 3. Indexed Fast Random Sampling for Reflex Drills
        if self._table_exists(conn, "reflex_drills"):
            q_reflex = """
                SELECT r.id, r.prompt_text, r.correct_answer, r.distractors_json, s.cefr_level
                FROM reflex_drills r
                JOIN sentences s ON r.sentence_id = s.id
                WHERE r.drill_type = 1
                  AND r.id >= (
                    SELECT ABS(RANDOM()) % (MAX(id) - MIN(id) + 1) + MIN(id)
                    FROM reflex_drills WHERE drill_type = 1
                  )
                LIMIT 1;
            """
            durations = []
            for _ in range(iterations):
                t0 = time.perf_counter()
                cursor.execute(q_reflex)
                cursor.fetchone()
                durations.append((time.perf_counter() - t0) * 1000.0)
            results["reflex_sampling_ms"] = round(sum(durations) / len(durations), 3) if durations else 0.0

        # 4. Topic & Word Relations JOIN
        if self._table_exists(conn, "words") and self._table_exists(conn, "word_topics") and self._table_exists(conn, "word_relations"):
            q_join = "SELECT w.id, w.lemma, wt.topic, wr.target_text FROM words w JOIN word_topics wt ON w.id = wt.word_id JOIN word_relations wr ON w.id = wr.word_id WHERE w.id = 1;"
            durations = []
            for _ in range(iterations):
                t0 = time.perf_counter()
                cursor.execute(q_join)
                cursor.fetchall()
                durations.append((time.perf_counter() - t0) * 1000.0)
            results["topic_relation_join_ms"] = round(sum(durations) / len(durations), 3) if durations else 0.0

        # 5. Pattern Sentences Lookup
        if self._table_exists(conn, "pattern_sentences") and self._table_exists(conn, "sentences"):
            cursor.execute("PRAGMA table_info(sentences);")
            s_cols = {col[1] for col in cursor.fetchall()}
            text_vi_clause = ", s.text_vi" if "text_vi" in s_cols else ""
            q_pattern = f"SELECT s.id, s.text_en{text_vi_clause} FROM pattern_sentences ps JOIN sentences s ON ps.sentence_id = s.id WHERE ps.pattern_id = 1 LIMIT 10;"
            durations = []
            for _ in range(iterations):
                t0 = time.perf_counter()
                cursor.execute(q_pattern)
                cursor.fetchall()
                durations.append((time.perf_counter() - t0) * 1000.0)
            results["pattern_lookup_ms"] = round(sum(durations) / len(durations), 3) if durations else 0.0

        conn.close()
        return results

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


