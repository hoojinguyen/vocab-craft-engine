from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.learning.catalog import RawRecordInput, SourceCatalog

FIRST_LEXICAL_POS = frozenset(
    {
        "noun",
        "verb",
        "adj",
        "adv",
        "prep",
        "pron",
        "det",
        "conj",
        "intj",
        "article",
        "num",
    }
)
FIRST_LEXICAL_LEMMA = re.compile(r"^[a-z]+(?:-[a-z]+)*$")
MAX_FREQUENCY_RANK = 3500
MAX_EXAMPLES_PER_WORD = 3
_HASH_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class SQLiteLexicalImportReport:
    """Outcome of one read-only lexical slice import."""

    source_snapshot_id: str
    import_run_id: str
    scanned_words: int
    eligible_words: int
    imported_or_existing_raw_records: int

    @property
    def imported_raw_records(self) -> int:
        """Compatibility name for records either newly inserted or already present."""
        return self.imported_or_existing_raw_records


class SQLiteLexicalReferenceImporter:
    """Read policy-eligible lexical bundles from an immutable SQLite reference."""

    def __init__(self, catalog: SourceCatalog) -> None:
        self.catalog = catalog

    def import_vertical_slice(
        self, reference_path: Path, snapshot_id: str, import_run_id: str
    ) -> SQLiteLexicalImportReport:
        source_path = Path(reference_path)
        if not source_path.exists():
            raise FileNotFoundError(source_path)
        asset_id = self._verify_source_snapshot(source_path, snapshot_id)

        connection = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        try:
            connection.execute("PRAGMA query_only = ON")
            words = connection.execute(
                """
                SELECT id, lemma, pos, frequency_rank, cefr_level, ipa_uk, ipa_us, source
                FROM words
                WHERE frequency_rank >= 1 AND frequency_rank <= ?
                ORDER BY frequency_rank, id
                """,
                [MAX_FREQUENCY_RANK],
            ).fetchall()
            records = [
                self._raw_record_for_word(connection, asset_id, word, import_run_id)
                for word in words
                if self._is_eligible(word[1], word[2])
            ]
        finally:
            connection.close()

        self.catalog.append_raw_records(records)
        return SQLiteLexicalImportReport(
            source_snapshot_id=snapshot_id,
            import_run_id=import_run_id,
            scanned_words=len(words),
            eligible_words=len(records),
            imported_or_existing_raw_records=len(records),
        )

    def _verify_source_snapshot(self, source_path: Path, snapshot_id: str) -> str:
        snapshot = (
            self.catalog.store.connection()
            .execute(
                """
            SELECT asset_id, local_path, file_sha256
            FROM source_snapshots
            WHERE snapshot_id = ?
            """,
                [snapshot_id],
            )
            .fetchone()
        )
        if snapshot is None:
            raise ValueError(f"source snapshot does not exist: {snapshot_id!r}")

        asset_id, snapshot_path, snapshot_sha256 = snapshot
        if Path(snapshot_path).resolve() != source_path.resolve():
            raise ValueError("source snapshot local path does not match reference path")
        if self._hash_file(source_path) != snapshot_sha256:
            raise ValueError("source snapshot checksum does not match reference path")
        return str(asset_id)

    @staticmethod
    def _is_eligible(lemma: object, pos: object) -> bool:
        if not isinstance(lemma, str) or not isinstance(pos, str):
            return False
        return (
            pos.strip().lower() in FIRST_LEXICAL_POS
            and FIRST_LEXICAL_LEMMA.fullmatch(lemma.strip().lower()) is not None
        )

    @classmethod
    def _raw_record_for_word(
        cls,
        connection: sqlite3.Connection,
        asset_id: str,
        word: tuple[Any, ...],
        import_run_id: str,
    ) -> RawRecordInput:
        (
            word_id,
            lemma,
            pos,
            frequency_rank,
            cefr_level,
            ipa_uk,
            ipa_us,
            source,
        ) = word
        definitions = [
            {
                "definition_en": definition_en,
                "definition_vi": definition_vi,
                "example": example,
                "source": definition_source,
            }
            for definition_en, definition_vi, example, definition_source in connection.execute(
                """
                SELECT definition_en, definition_vi, example, source
                FROM definitions
                WHERE word_id = ?
                ORDER BY id
                """,
                [word_id],
            ).fetchall()
        ]
        examples = [
            {"text_en": text_en, "text_vi": text_vi, "source": sentence_source}
            for text_en, text_vi, sentence_source in connection.execute(
                """
                SELECT sentences.text_en, sentences.text_vi, sentences.source
                FROM word_sentences
                JOIN sentences ON sentences.id = word_sentences.sentence_id
                WHERE word_sentences.word_id = ?
                  AND sentences.text_en IS NOT NULL
                  AND sentences.text_vi IS NOT NULL
                ORDER BY word_sentences.sentence_id
                LIMIT ?
                """,
                [word_id, MAX_EXAMPLES_PER_WORD],
            ).fetchall()
        ]
        normalized_lemma = lemma.strip().lower()
        normalized_pos = pos.strip().lower()
        return RawRecordInput(
            asset_id=asset_id,
            external_key=f"sqlite-lexical:{word_id}",
            record_type="sqlite_lexical_bundle",
            payload={
                "word": {
                    "legacy_word_id": word_id,
                    "lemma": normalized_lemma,
                    "pos": normalized_pos,
                    "frequency_rank": frequency_rank,
                    "cefr_level": cefr_level,
                    "ipa_uk": ipa_uk,
                    "ipa_us": ipa_us,
                    "source": source,
                },
                "definitions": definitions,
                "examples": examples,
            },
            import_run_id=import_run_id,
        )

    @staticmethod
    def _hash_file(source_path: Path) -> str:
        digest = hashlib.sha256()
        with source_path.open("rb") as source_file:
            while chunk := source_file.read(_HASH_CHUNK_SIZE):
                digest.update(chunk)
        return digest.hexdigest()
