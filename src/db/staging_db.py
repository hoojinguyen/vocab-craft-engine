"""
Staging Database Manager for English Dataset System Engine.
Handles schema initialization, batch insertions, idempotency, and transaction management.
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import logging

from config.settings import EXPORT_SQLITE_PATH, BATCH_SIZE

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQLite database connections, schema creation, and idempotent batch writes."""

    def __init__(self, db_path: Path = EXPORT_SQLITE_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None

    def get_connection(self) -> sqlite3.Connection:
        if self.conn is None:
            self.conn = sqlite3.connect(str(self.db_path))
            self.conn.execute("PRAGMA foreign_keys = ON;")
        return self.conn

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def enable_fast_staging_mode(self):
        """Enables high-performance SQLite PRAGMAs for fast staging database operations."""
        conn = self.get_connection()
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA cache_size = -64000;")
        conn.execute("PRAGMA temp_store = MEMORY;")


    def init_schema(self):
        """Initializes relational database tables and composite indexes."""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 1. Words table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lemma TEXT UNIQUE NOT NULL,
                pos TEXT NOT NULL,
                ipa_uk TEXT,
                ipa_us TEXT,
                frequency_rank INTEGER,
                cefr_level TEXT
            );
        """)

        # 2. Definitions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_id INTEGER NOT NULL,
                definition_en TEXT,
                definition_vi TEXT,
                example TEXT,
                source TEXT,
                FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE
            );
        """)

        # 3. Collocations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS collocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phrase TEXT UNIQUE NOT NULL,
                meaning_vi TEXT,
                pos_pattern TEXT,
                cefr_level TEXT
            );
        """)

        # 4. Sentence Patterns table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sentence_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_name TEXT UNIQUE NOT NULL,
                structure_json TEXT,
                example_en TEXT,
                example_vi TEXT,
                cefr_level TEXT
            );
        """)

        # 5. Sentences table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sentences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text_en TEXT UNIQUE NOT NULL,
                text_vi TEXT,
                difficulty_score REAL,
                cefr_level TEXT,
                audio_path TEXT,
                source TEXT
            );
        """)

        # 6. Dialogue Trees table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dialogue_trees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                topic TEXT,
                cefr_level TEXT,
                root_node_id INTEGER
            );
        """)

        # 7. Dialogue Nodes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dialogue_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tree_id INTEGER NOT NULL,
                parent_node_id INTEGER,
                choice_label TEXT,
                speaker_role TEXT NOT NULL,
                sentence_id INTEGER,
                FOREIGN KEY (tree_id) REFERENCES dialogue_trees (id) ON DELETE CASCADE,
                FOREIGN KEY (parent_node_id) REFERENCES dialogue_nodes (id) ON DELETE CASCADE,
                FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE SET NULL
            );
        """)

        # 8. Reflex Drills table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reflex_drills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sentence_id INTEGER NOT NULL,
                drill_type TEXT NOT NULL,
                prompt_text TEXT,
                correct_answer TEXT NOT NULL,
                distractors_json TEXT,
                target_time_ms INTEGER DEFAULT 2500,
                FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE CASCADE
            );
        """)

        # 9. Word - Sentence Map table (N - N)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS word_sentence_map (
                word_id INTEGER NOT NULL,
                sentence_id INTEGER NOT NULL,
                PRIMARY KEY (word_id, sentence_id),
                FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE,
                FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE CASCADE
            );
        """)

        # 10. Phrases table (multi-word expressions)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS phrases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phrase TEXT UNIQUE NOT NULL,
                phrase_type TEXT NOT NULL,
                pos TEXT,
                cefr_level TEXT,
                difficulty_score REAL,
                definition_en TEXT,
                definition_vi TEXT,
                ipa TEXT,
                audio_std TEXT,
                audio_fast TEXT,
                audio_status TEXT DEFAULT 'ok'
            );
        """)

        # 11. Phrase - Sentence Map table (N - N)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS phrase_sentences (
                phrase_id INTEGER NOT NULL,
                sentence_id INTEGER NOT NULL,
                rank INTEGER,
                PRIMARY KEY (phrase_id, sentence_id),
                FOREIGN KEY (phrase_id) REFERENCES phrases (id) ON DELETE CASCADE,
                FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE CASCADE
            );
        """)

        # 12. Word Lexical Relations table (N-1 to words, self-referencing)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS word_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL,
                target_text TEXT NOT NULL,
                target_word_id INTEGER,
                inverted INTEGER NOT NULL DEFAULT 0,
                source TEXT,
                FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE,
                FOREIGN KEY (target_word_id) REFERENCES words (id) ON DELETE CASCADE
            );
        """)

        # 13. Word Topics table (N-1 to words)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS word_topics (
                word_id INTEGER NOT NULL,
                topic TEXT NOT NULL,
                raw_topic TEXT,
                FOREIGN KEY (word_id) REFERENCES words (id) ON DELETE CASCADE
            );
        """)

        # 14. Pattern - Sentence Map table (N - N)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pattern_sentences (
                pattern_id INTEGER NOT NULL,
                sentence_id INTEGER NOT NULL,
                matched_tokens_json TEXT,
                PRIMARY KEY (pattern_id, sentence_id),
                FOREIGN KEY (pattern_id) REFERENCES sentence_patterns (id) ON DELETE CASCADE,
                FOREIGN KEY (sentence_id) REFERENCES sentences (id) ON DELETE CASCADE
            ) WITHOUT ROWID;
        """)

        # 15. Quiz Questions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quiz_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_type TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id INTEGER,
                prompt_text TEXT NOT NULL,
                correct_answer TEXT NOT NULL,
                options_json TEXT NOT NULL,
                cefr_level TEXT NOT NULL DEFAULT 'B1'
            );
        """)

        # Indexes for fast mobile and pipeline queries
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_words_lemma ON words(lemma);")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sentences_text_en ON sentences(text_en);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reflex_cefr_type ON reflex_drills(drill_type, sentence_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_nodes_tree_parent ON dialogue_nodes(tree_id, parent_node_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrases_cefr ON phrases(cefr_level);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrases_type ON phrases(phrase_type);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrase_sentences_phrase ON phrase_sentences(phrase_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phrase_sentences_sentence ON phrase_sentences(sentence_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pattern_sentences_sentence ON pattern_sentences(sentence_id);")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_word_relations_unique ON word_relations(word_id, relation_type, target_text);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_word_relations_target ON word_relations(target_word_id);")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_word_topics_unique ON word_topics(word_id, topic);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_word_topics_topic ON word_topics(topic);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_definitions_word_id ON definitions(word_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quiz_type_cefr ON quiz_questions(question_type, cefr_level);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quiz_target ON quiz_questions(target_type, target_id);")

        conn.commit()
        logger.info("Database schema initialized successfully at %s", self.db_path)

    def insert_words_batch(self, words_data: List[Dict[str, Any]]) -> int:
        """Batch insert words into `words` table with IGNORE on duplicate lemma."""
        if not words_data:
            return 0

        conn = self.get_connection()
        query = """
            INSERT OR IGNORE INTO words (lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level)
            VALUES (:lemma, :pos, :ipa_uk, :ipa_us, :frequency_rank, :cefr_level);
        """
        cursor = conn.cursor()
        cursor.executemany(query, words_data)
        conn.commit()
        return cursor.rowcount

    def insert_definitions_batch(self, definitions_data: List[Dict[str, Any]]) -> int:
        """Batch insert definitions into `definitions` table."""
        if not definitions_data:
            return 0

        conn = self.get_connection()
        query = """
            INSERT INTO definitions (word_id, definition_en, definition_vi, example, source)
            VALUES (:word_id, :definition_en, :definition_vi, :example, :source);
        """
        cursor = conn.cursor()
        cursor.executemany(query, definitions_data)
        conn.commit()
        return cursor.rowcount

    def insert_sentences_batch(self, sentences_data: List[Dict[str, Any]]) -> int:
        """Batch insert sentences into `sentences` table."""
        if not sentences_data:
            return 0

        conn = self.get_connection()
        query = """
            INSERT OR IGNORE INTO sentences (text_en, text_vi, difficulty_score, cefr_level, audio_path, source)
            VALUES (:text_en, :text_vi, :difficulty_score, :cefr_level, :audio_path, :source);
        """
        cursor = conn.cursor()
        cursor.executemany(query, sentences_data)
        conn.commit()
        return cursor.rowcount

    def insert_collocations_batch(self, collocations_data: List[Dict[str, Any]]) -> int:
        """Batch insert collocations into `collocations` table."""
        if not collocations_data:
            return 0

        conn = self.get_connection()
        query = """
            INSERT OR IGNORE INTO collocations (phrase, meaning_vi, pos_pattern, cefr_level)
            VALUES (:phrase, :meaning_vi, :pos_pattern, :cefr_level);
        """
        cursor = conn.cursor()
        cursor.executemany(query, collocations_data)
        conn.commit()
        return cursor.rowcount

    def insert_sentence_patterns_batch(self, patterns_data: List[Dict[str, Any]]) -> int:
        """Batch insert sentence patterns into `sentence_patterns` table."""
        if not patterns_data:
            return 0

        conn = self.get_connection()
        query = """
            INSERT OR IGNORE INTO sentence_patterns (pattern_name, structure_json, example_en, example_vi, cefr_level)
            VALUES (:pattern_name, :structure_json, :example_en, :example_vi, :cefr_level);
        """
        cursor = conn.cursor()
        cursor.executemany(query, patterns_data)
        conn.commit()
        return cursor.rowcount

    def insert_pattern_sentences_batch(self, mappings: List[Dict[str, Any]]) -> int:
        """Batch insert pattern to sentence mappings into `pattern_sentences` table."""
        if not mappings:
            return 0
        conn = self.get_connection()
        cursor = conn.cursor()
        query = """
            INSERT OR IGNORE INTO pattern_sentences (pattern_id, sentence_id, matched_tokens_json)
            VALUES (:pattern_id, :sentence_id, :matched_tokens_json);
        """
        cursor.executemany(query, mappings)
        conn.commit()
        return cursor.rowcount

    def insert_word_sentence_map_batch(self, mappings_data: List[Dict[str, Any]]) -> int:
        """Batch insert mappings into `word_sentence_map` table."""
        if not mappings_data:
            return 0

        conn = self.get_connection()
        query = """
            INSERT OR IGNORE INTO word_sentence_map (word_id, sentence_id)
            VALUES (:word_id, :sentence_id);
        """
        cursor = conn.cursor()
        cursor.executemany(query, mappings_data)
        conn.commit()
        return cursor.rowcount

    def get_word_id_by_lemma(self, lemma: str) -> Optional[int]:
        """Fetch word_id for a given lemma."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM words WHERE lemma = ? LIMIT 1;", (lemma,))
        row = cursor.fetchone()
        return row[0] if row else None

    def get_max_sentence_id(self) -> int:
        conn = self.get_connection()
        row = conn.execute("SELECT MAX(id) FROM sentences").fetchone()
        return row[0] if row and row[0] else 0

    def count_sentences_by_source(self, source: str) -> int:
        conn = self.get_connection()
        row = conn.execute("SELECT count(*) FROM sentences WHERE source = ?", (source,)).fetchone()
        return row[0] if row else 0

    def insert_phrases_batch(self, phrases_data: List[Dict[str, Any]]) -> int:
        """Batch insert phrases into `phrases` table with IGNORE on duplicate phrase."""
        if not phrases_data:
            return 0

        conn = self.get_connection()
        query = """
            INSERT OR IGNORE INTO phrases
            (phrase, phrase_type, pos, cefr_level, difficulty_score, definition_en,
             definition_vi, ipa, audio_std, audio_fast, audio_status)
            VALUES (:phrase, :phrase_type, :pos, :cefr_level, :difficulty_score,
                    :definition_en, :definition_vi, :ipa, :audio_std, :audio_fast, :audio_status);
        """
        cursor = conn.cursor()
        cursor.executemany(query, phrases_data)
        conn.commit()
        return cursor.rowcount

    def get_phrase_id_by_text(self, phrase: str) -> Optional[int]:
        """Fetch phrase_id for a given phrase text."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM phrases WHERE phrase = ? LIMIT 1;", (phrase,))
        row = cursor.fetchone()
        return row[0] if row else None

    def insert_phrase_sentences_batch(self, mappings_data: List[Dict[str, Any]]) -> int:
        """Batch insert mappings into `phrase_sentences` table."""
        if not mappings_data:
            return 0

        conn = self.get_connection()
        query = """
            INSERT OR IGNORE INTO phrase_sentences (phrase_id, sentence_id, rank)
            VALUES (:phrase_id, :sentence_id, :rank);
        """
        cursor = conn.cursor()
        cursor.executemany(query, mappings_data)
        conn.commit()
        return cursor.rowcount

    def insert_word_relations_batch(self, relations_data: List[Dict[str, Any]]) -> int:
        """Batch insert lexical relations with IGNORE on duplicate (word_id, relation_type, target_text)."""
        if not relations_data:
            return 0

        conn = self.get_connection()
        query = """
            INSERT OR IGNORE INTO word_relations (word_id, relation_type, target_text, target_word_id, inverted, source)
            VALUES (:word_id, :relation_type, :target_text, :target_word_id, :inverted, :source);
        """
        cursor = conn.cursor()
        cursor.executemany(query, relations_data)
        conn.commit()
        return cursor.rowcount

    def insert_word_topics_batch(self, topics_data: List[Dict[str, Any]]) -> int:
        """Batch topic insert with IGNORE on duplicate (word_id, topic)."""
        if not topics_data:
            return 0

        conn = self.get_connection()
        query = """
            INSERT OR IGNORE INTO word_topics (word_id, topic, raw_topic)
            VALUES (:word_id, :topic, :raw_topic);
        """
        cursor = conn.cursor()
        cursor.executemany(query, topics_data)
        conn.commit()
        return cursor.rowcount

    def update_phrase_audio(self, phrase_id: int, audio_std: Optional[str],
                            audio_fast: Optional[str], audio_status: str = "ok") -> None:
        """Update audio paths and status for a phrase."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE phrases SET audio_std = ?, audio_fast = ?, audio_status = ? WHERE id = ?;",
            (audio_std, audio_fast, audio_status, phrase_id)
        )
        conn.commit()

    def _get_or_create_sentence(
        self,
        cursor: sqlite3.Cursor,
        text_en: str,
        text_vi: Optional[str] = None,
        cefr_level: Optional[str] = None,
        source: str = "dialogue_generator",
    ) -> int:
        """Helper to find existing sentence by text_en or insert a new sentence record."""
        cursor.execute("SELECT id, text_vi FROM sentences WHERE text_en = ? LIMIT 1;", (text_en,))
        row = cursor.fetchone()
        if row:
            sent_id, existing_vi = row[0], row[1]
            if not existing_vi and text_vi:
                cursor.execute("UPDATE sentences SET text_vi = ? WHERE id = ?;", (text_vi, sent_id))
            return sent_id
        cursor.execute(
            """
            INSERT INTO sentences (text_en, text_vi, cefr_level, source)
            VALUES (?, ?, ?, ?);
            """,
            (text_en, text_vi, cefr_level, source),
        )
        return cursor.lastrowid

    def insert_dialogue_scenarios_batch(self, scenarios: List[Dict[str, Any]]) -> Tuple[int, int]:
        """Batch insert dialogue scenarios (trees and nodes) with sentence auto-linking."""
        if not scenarios:
            return 0, 0

        conn = self.get_connection()
        cursor = conn.cursor()

        total_trees = 0
        total_nodes = 0

        with conn:
            for scenario in scenarios:
                title = scenario.get("title", "")
                topic = scenario.get("topic")
                cefr_level = scenario.get("cefr_level")
                nodes = scenario.get("nodes", [])

                cursor.execute(
                    "INSERT INTO dialogue_trees (title, topic, cefr_level) VALUES (?, ?, ?);",
                    (title, topic, cefr_level),
                )
                tree_id = cursor.lastrowid
                total_trees += 1

                index_to_db_id: Dict[int, int] = {}
                root_node_id: Optional[int] = None

                sorted_nodes = sorted(nodes, key=lambda n: n.get("node_index", 0))

                for node in sorted_nodes:
                    node_idx = node.get("node_index", 0)
                    parent_idx = node.get("parent_index")
                    speaker_role = node.get("speaker_role", "")
                    choice_label = node.get("choice_label")
                    text_en = node.get("text_en", "")
                    text_vi = node.get("text_vi")

                    sentence_id = self._get_or_create_sentence(
                        cursor,
                        text_en=text_en,
                        text_vi=text_vi,
                        cefr_level=cefr_level,
                        source="dialogue_generator",
                    )

                    parent_db_id = index_to_db_id.get(parent_idx) if parent_idx is not None else None

                    cursor.execute(
                        """
                        INSERT INTO dialogue_nodes (tree_id, parent_node_id, choice_label, speaker_role, sentence_id)
                        VALUES (?, ?, ?, ?, ?);
                        """,
                        (tree_id, parent_db_id, choice_label, speaker_role, sentence_id),
                    )
                    db_node_id = cursor.lastrowid
                    index_to_db_id[node_idx] = db_node_id
                    total_nodes += 1

                    if node_idx == 0:
                        root_node_id = db_node_id

                if root_node_id is not None:
                    cursor.execute(
                        "UPDATE dialogue_trees SET root_node_id = ? WHERE id = ?;",
                        (root_node_id, tree_id),
                    )

        return total_trees, total_nodes

    def insert_quiz_questions_batch(self, questions: List[Dict[str, Any]]) -> int:
        """Batch insert quiz questions into `quiz_questions` table."""
        if not questions:
            return 0

        prepared_questions = []
        for q in questions:
            prepared_questions.append({
                "question_type": q["question_type"],
                "target_type": q["target_type"],
                "target_id": q.get("target_id"),
                "prompt_text": q["prompt_text"],
                "correct_answer": q["correct_answer"],
                "options_json": q["options_json"],
                "cefr_level": q.get("cefr_level") or "B1",
            })

        conn = self.get_connection()
        query = """
            INSERT INTO quiz_questions
            (question_type, target_type, target_id, prompt_text, correct_answer, options_json, cefr_level)
            VALUES
            (:question_type, :target_type, :target_id, :prompt_text, :correct_answer, :options_json, :cefr_level);
        """
        cursor = conn.cursor()
        cursor.executemany(query, prepared_questions)
        conn.commit()
        return cursor.rowcount


