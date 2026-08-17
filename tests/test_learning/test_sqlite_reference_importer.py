from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.learning import sqlite_reference_importer
from src.learning.catalog import RawRecordInput, SourceCatalog
from src.learning.models import ReviewState, SourceAssetInput
from src.learning.sqlite_reference_importer import SQLiteLexicalReferenceImporter
from src.learning.store import LearningGraphStore


@pytest.fixture
def catalog(tmp_path: Path) -> SourceCatalog:
    store = LearningGraphStore(tmp_path / "graph.duckdb")
    store.initialize()
    return SourceCatalog(store)


@pytest.fixture
def legacy_sqlite(tmp_path: Path) -> Path:
    path = tmp_path / "english_dataset.db"
    connection = sqlite3.connect(path)
    try:
        connection.executescript("""
            CREATE TABLE words (
                id INTEGER PRIMARY KEY,
                lemma TEXT NOT NULL,
                pos TEXT NOT NULL,
                ipa_uk TEXT,
                ipa_us TEXT,
                frequency_rank INTEGER,
                cefr_level TEXT,
                source TEXT
            );
            CREATE TABLE definitions (
                id INTEGER PRIMARY KEY,
                word_id INTEGER NOT NULL,
                definition_en TEXT,
                definition_vi TEXT,
                example TEXT,
                source TEXT
            );
            CREATE TABLE sentences (
                id INTEGER PRIMARY KEY,
                text_en TEXT NOT NULL,
                text_vi TEXT,
                difficulty_score REAL,
                cefr_level TEXT,
                audio_path TEXT,
                source TEXT
            );
            CREATE TABLE word_sentences (
                word_id INTEGER NOT NULL,
                sentence_id INTEGER NOT NULL,
                rank INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (word_id, sentence_id)
            );
            """)
        connection.executemany(
            """
            INSERT INTO words (
                id, lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (10, "book", "noun", "/bʊk/", "/bʊk/", 100, "A1", "kaikki"),
                (11, "Book Name", "noun", None, None, 200, "A1", "kaikki"),
                (12, "rareword", "noun", None, None, 4000, "B2", "kaikki"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO definitions (
                id, word_id, definition_en, definition_vi, example, source
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    1,
                    10,
                    "A set of written pages.",
                    "quyển sách",
                    "Read a book.",
                    "kaikki",
                ),
                (2, 10, "A written work.", "tác phẩm", None, "kaikki"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO sentences (
                id, text_en, text_vi, difficulty_score, cefr_level, audio_path, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    30,
                    "That book is old.",
                    "Quyển sách đó cũ.",
                    None,
                    "A1",
                    None,
                    "tatoeba",
                ),
                (
                    10,
                    "Read this book.",
                    "Hãy đọc quyển sách này.",
                    None,
                    "A1",
                    None,
                    "tatoeba",
                ),
                (
                    20,
                    "The book is here.",
                    "Quyển sách ở đây.",
                    None,
                    "A1",
                    None,
                    "tatoeba",
                ),
            ],
        )
        connection.executemany(
            "INSERT INTO word_sentences (word_id, sentence_id, rank) VALUES (?, ?, ?)",
            [(10, 30, 1), (10, 10, 2), (10, 20, 3)],
        )
        connection.commit()
    finally:
        connection.close()
    return path


@pytest.fixture
def approved_snapshot_id(catalog: SourceCatalog, legacy_sqlite: Path) -> str:
    checksum = hashlib.sha256(legacy_sqlite.read_bytes()).hexdigest()
    source = SourceAssetInput(
        asset_id="sqlite-reference",
        title="Immutable SQLite reference",
        locator="https://example.test/english-dataset",
        asset_version="2026-08",
        sha256=checksum,
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution="Example author",
        redistribution_allowed=True,
        validation_status=ReviewState.APPROVED,
    )
    catalog.register_source(source)
    return catalog.record_source_snapshot(
        source.asset_id, legacy_sqlite, datetime(2026, 8, 17, tzinfo=UTC)
    )


def test_import_vertical_slice_snapshots_only_policy_eligible_lexical_bundles(
    catalog: SourceCatalog, legacy_sqlite: Path, approved_snapshot_id: str
):
    before_sha256 = hashlib.sha256(legacy_sqlite.read_bytes()).hexdigest()
    before_mtime_ns = legacy_sqlite.stat().st_mtime_ns

    report = SQLiteLexicalReferenceImporter(catalog).import_vertical_slice(
        legacy_sqlite, approved_snapshot_id, "run-2026-08-17"
    )

    assert report.source_snapshot_id == approved_snapshot_id
    assert report.import_run_id == "run-2026-08-17"
    assert report.scanned_words == 2
    assert report.eligible_words == 1
    assert report.imported_or_existing_raw_records == 1
    raw_record = catalog.store.connection().execute("""
        SELECT external_key, record_type, payload_json
        FROM raw_reference_records
        """).fetchone()
    assert raw_record is not None
    external_key, record_type, payload_json = raw_record
    assert external_key == "sqlite-lexical:10"
    assert record_type == "sqlite_lexical_bundle"
    assert json.loads(payload_json) == {
        "word": {
            "legacy_word_id": 10,
            "lemma": "book",
            "pos": "noun",
            "frequency_rank": 100,
            "cefr_level": "A1",
            "ipa_uk": "/bʊk/",
            "ipa_us": "/bʊk/",
            "source": "kaikki",
        },
        "definitions": [
            {
                "definition_en": "A set of written pages.",
                "definition_vi": "quyển sách",
                "example": "Read a book.",
                "source": "kaikki",
            },
            {
                "definition_en": "A written work.",
                "definition_vi": "tác phẩm",
                "example": None,
                "source": "kaikki",
            },
        ],
        "examples": [
            {
                "text_en": "Read this book.",
                "text_vi": "Hãy đọc quyển sách này.",
                "source": "tatoeba",
            },
            {
                "text_en": "The book is here.",
                "text_vi": "Quyển sách ở đây.",
                "source": "tatoeba",
            },
            {
                "text_en": "That book is old.",
                "text_vi": "Quyển sách đó cũ.",
                "source": "tatoeba",
            },
        ],
    }
    assert hashlib.sha256(legacy_sqlite.read_bytes()).hexdigest() == before_sha256
    assert legacy_sqlite.stat().st_mtime_ns == before_mtime_ns


def test_import_vertical_slice_is_idempotent(
    catalog: SourceCatalog, legacy_sqlite: Path, approved_snapshot_id: str
):
    importer = SQLiteLexicalReferenceImporter(catalog)

    first_report = importer.import_vertical_slice(
        legacy_sqlite, approved_snapshot_id, "run-first"
    )
    second_report = importer.import_vertical_slice(
        legacy_sqlite, approved_snapshot_id, "run-second"
    )

    assert first_report.imported_or_existing_raw_records == 1
    assert second_report.imported_or_existing_raw_records == 1
    assert catalog.store.fetch_value("SELECT count(*) FROM raw_reference_records") == 1


def test_import_vertical_slice_rejects_a_missing_reference_path(
    catalog: SourceCatalog, tmp_path: Path, approved_snapshot_id: str
):
    with pytest.raises(FileNotFoundError):
        SQLiteLexicalReferenceImporter(catalog).import_vertical_slice(
            tmp_path / "missing.db", approved_snapshot_id, "run-missing"
        )


def test_import_vertical_slice_rejects_a_snapshot_path_mismatch(
    catalog: SourceCatalog,
    legacy_sqlite: Path,
    approved_snapshot_id: str,
    tmp_path: Path,
):
    copied_path = tmp_path / "same-content-different-path.db"
    copied_path.write_bytes(legacy_sqlite.read_bytes())

    with pytest.raises(ValueError, match="local path"):
        SQLiteLexicalReferenceImporter(catalog).import_vertical_slice(
            copied_path, approved_snapshot_id, "run-mismatch"
        )


def test_import_vertical_slice_rejects_volatile_sqlite_sidecars(
    catalog: SourceCatalog, legacy_sqlite: Path, approved_snapshot_id: str
):
    wal_path = Path(f"{legacy_sqlite}-wal")
    wal_path.write_bytes(b"volatile wal")
    try:
        with pytest.raises(ValueError, match="volatile sidecar"):
            SQLiteLexicalReferenceImporter(catalog).import_vertical_slice(
                legacy_sqlite, approved_snapshot_id, "run-wal"
            )
    finally:
        wal_path.unlink()


@pytest.mark.parametrize(
    "filename",
    ["reference?version=1.db", "reference#fragment.db", "reference%percent.db"],
)
def test_import_vertical_slice_uses_the_verified_path_for_uri_special_characters(
    catalog: SourceCatalog,
    legacy_sqlite: Path,
    tmp_path: Path,
    filename: str,
):
    reference_path = tmp_path / filename
    reference_path.write_bytes(legacy_sqlite.read_bytes())
    checksum = hashlib.sha256(reference_path.read_bytes()).hexdigest()
    catalog.register_source(
        SourceAssetInput(
            asset_id=f"sqlite-special-{len(filename)}",
            title="Special-path SQLite reference",
            locator="https://example.test/special-path",
            asset_version="2026-08",
            sha256=checksum,
            license_id="CC-BY-4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            attribution="Example author",
            redistribution_allowed=True,
            validation_status=ReviewState.APPROVED,
        )
    )
    snapshot_id = catalog.record_source_snapshot(
        f"sqlite-special-{len(filename)}",
        reference_path,
        datetime(2026, 8, 17, tzinfo=UTC),
    )

    report = SQLiteLexicalReferenceImporter(catalog).import_vertical_slice(
        reference_path, snapshot_id, "run-special-path"
    )

    assert report.eligible_words == 1
    assert (
        catalog.store.fetch_value("SELECT external_key FROM raw_reference_records")
        == "sqlite-lexical:10"
    )


def test_import_vertical_slice_reads_only_the_verified_private_copy(
    catalog: SourceCatalog,
    legacy_sqlite: Path,
    approved_snapshot_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    trusted_bytes = legacy_sqlite.read_bytes()
    tampered_path = tmp_path / "tampered.db"
    tampered_path.write_bytes(trusted_bytes)
    connection = sqlite3.connect(tampered_path)
    try:
        connection.execute("UPDATE words SET lemma = 'tampered' WHERE id = 10")
        connection.commit()
    finally:
        connection.close()
    tampered_bytes = tampered_path.read_bytes()

    original_connect = sqlite_reference_importer.sqlite3.connect

    def swap_source_on_sqlite_open(
        database: str | Path, *args: object, **kwargs: object
    ) -> sqlite3.Connection:
        if "lexical-reference-" in str(database):
            legacy_sqlite.write_bytes(tampered_bytes)
            connection = original_connect(database, *args, **kwargs)
            legacy_sqlite.write_bytes(trusted_bytes)
            return connection
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(
        sqlite_reference_importer.sqlite3, "connect", swap_source_on_sqlite_open
    )

    SQLiteLexicalReferenceImporter(catalog).import_vertical_slice(
        legacy_sqlite, approved_snapshot_id, "run-swap-on-open"
    )

    payload_json = catalog.store.fetch_value(
        "SELECT payload_json FROM raw_reference_records"
    )
    assert json.loads(payload_json)["word"]["lemma"] == "book"


def test_append_raw_records_batches_250_records_and_is_idempotent(
    catalog: SourceCatalog,
    legacy_sqlite: Path,
    approved_snapshot_id: str,
    monkeypatch: pytest.MonkeyPatch,
):
    transaction_calls = 0
    transaction = catalog.store.transaction

    @contextmanager
    def counting_transaction() -> Iterator[object]:
        nonlocal transaction_calls
        transaction_calls += 1
        with transaction() as connection:
            yield connection

    monkeypatch.setattr(catalog.store, "transaction", counting_transaction)
    records = tuple(
        RawRecordInput(
            asset_id="sqlite-reference",
            external_key=f"test-batch:{index}",
            record_type="test_batch",
            payload={"index": index},
            import_run_id="batch-run",
        )
        for index in range(251)
    )

    first_ids = catalog.append_raw_records(records)

    assert len(first_ids) == 251
    assert transaction_calls == 2
    assert (
        catalog.store.fetch_value("SELECT count(*) FROM raw_reference_records") == 251
    )
    assert catalog.append_raw_records(records) == first_ids
    assert (
        catalog.store.fetch_value("SELECT count(*) FROM raw_reference_records") == 251
    )
