import hashlib

import duckdb

from src.learning.reference_importer import LegacyReferenceImporter


def test_snapshot_import_reads_legacy_db_without_mutating_it(graph_catalog, tmp_path):
    legacy_path = tmp_path / "staging.duckdb"
    legacy = duckdb.connect(str(legacy_path))
    legacy.execute("CREATE TABLE words(id INTEGER, lemma TEXT, pos TEXT, source TEXT)")
    legacy.execute("INSERT INTO words VALUES (1, 'hello', 'noun', 'kaikki')")
    legacy.close()
    before_sha256 = hashlib.sha256(legacy_path.read_bytes()).hexdigest()

    imported = LegacyReferenceImporter(graph_catalog).import_words(
        legacy_path, "human-authored-a0", "legacy-test"
    )

    assert imported == 1
    readonly = duckdb.connect(str(legacy_path), read_only=True)
    assert readonly.execute("SELECT * FROM words").fetchall() == [
        (1, "hello", "noun", "kaikki")
    ]
    readonly.close()
    assert hashlib.sha256(legacy_path.read_bytes()).hexdigest() == before_sha256
    assert (
        graph_catalog.store.fetch_value("SELECT count(*) FROM raw_reference_records")
        == 1
    )


def test_snapshot_import_is_idempotent(graph_catalog, tmp_path):
    legacy_path = tmp_path / "staging.duckdb"
    legacy = duckdb.connect(str(legacy_path))
    legacy.execute("CREATE TABLE words(id INTEGER, lemma TEXT, pos TEXT, source TEXT)")
    legacy.execute("INSERT INTO words VALUES (1, 'hello', 'noun', 'kaikki')")
    legacy.close()

    importer = LegacyReferenceImporter(graph_catalog)
    assert importer.import_words(legacy_path, "human-authored-a0", "first") == 1
    assert importer.import_words(legacy_path, "human-authored-a0", "second") == 1
    assert (
        graph_catalog.store.fetch_value("SELECT count(*) FROM raw_reference_records")
        == 1
    )
