from __future__ import annotations

import hashlib
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from config import settings
from src.learning import sqlite_reference_importer
from src.learning.catalog import SourceCatalog
from src.learning.models import ReviewState, SourceAssetInput
from src.learning.sqlite_reference_importer import (
    SQLiteLexicalReferenceImporter,
    SQLiteReferenceMaterializer,
)
from src.learning.store import LearningGraphStore


@pytest.fixture
def catalog(tmp_path: Path) -> SourceCatalog:
    store = LearningGraphStore(tmp_path / "graph.duckdb")
    store.initialize()
    return SourceCatalog(store)


@pytest.fixture
def wal_reference(tmp_path: Path) -> Path:
    path = tmp_path / "reference.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(
        "CREATE TABLE words (id INTEGER PRIMARY KEY, lemma TEXT, pos TEXT, frequency_rank INTEGER, source TEXT)"
    )
    connection.execute("INSERT INTO words VALUES (1, 'book', 'noun', 1, 'fixture')")
    connection.commit()
    connection.close()
    return path


def test_materializer_creates_a_queryable_snapshot_and_registers_derived_asset(
    catalog: SourceCatalog, wal_reference: Path, tmp_path: Path
):
    source = SourceAssetInput(
        asset_id="sqlite-reference",
        title="Reference",
        locator="https://example.test/reference",
        asset_version="2026-08",
        sha256=SQLiteReferenceMaterializer.hash_file(wal_reference),
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution="Fixture",
        redistribution_allowed=True,
        validation_status=ReviewState.APPROVED,
    )
    catalog.register_source(source)
    source_snapshot_id = catalog.record_source_snapshot(
        source.asset_id, wal_reference, datetime.now(UTC)
    )

    result = SQLiteReferenceMaterializer(catalog, tmp_path / "snapshots").materialize(
        wal_reference, source_snapshot_id
    )

    assert result.materialized_path.exists()
    assert result.derived_asset_id == (
        f"sqlite-reference.materialized.{result.materialized_sha256[:12]}"
    )
    assert result.snapshot_id
    with sqlite3.connect(result.materialized_path) as connection:
        assert connection.execute("SELECT lemma FROM words").fetchone() == ("book",)

    wal_path = Path(f"{result.materialized_path}-wal")
    wal_path.write_bytes(b"untrusted sidecar")
    with pytest.raises(ValueError, match="sidecar"):
        SQLiteLexicalReferenceImporter(catalog).import_ranked_definitions(
            result.materialized_path, result.snapshot_id, "sidecar-rejected"
        )


def test_materializer_uses_the_configured_snapshot_root(
    catalog: SourceCatalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    configured_root = tmp_path / "configured-snapshots"
    monkeypatch.setattr(settings, "LEXICAL_53K_SNAPSHOT_DIR", configured_root)

    assert SQLiteReferenceMaterializer(catalog).output_root == configured_root


def test_materializer_preserves_live_wal_sidecars_and_provenance(
    catalog: SourceCatalog, tmp_path: Path
):
    reference_path = tmp_path / "live-reference.db"
    source = sqlite3.connect(reference_path)
    try:
        assert source.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        source.execute("CREATE TABLE entries (value TEXT NOT NULL)")
        source.commit()
        main_sha256 = hashlib.sha256(reference_path.read_bytes()).hexdigest()
        catalog.register_source(
            SourceAssetInput(
                asset_id="live-wal-reference",
                title="Live WAL reference",
                locator="https://example.test/live-wal",
                asset_version="2026-08",
                sha256=main_sha256,
                license_id="CC-BY-4.0",
                license_url="https://creativecommons.org/licenses/by/4.0/",
                attribution="Fixture",
                redistribution_allowed=True,
                validation_status=ReviewState.APPROVED,
            )
        )
        source_snapshot_id = catalog.record_source_snapshot(
            "live-wal-reference", reference_path, datetime.now(UTC)
        )
        source.execute("INSERT INTO entries VALUES ('visible only through WAL')")
        source.commit()
        original_files = {
            suffix: (
                Path(f"{reference_path}{suffix}").read_bytes(),
                Path(f"{reference_path}{suffix}").stat().st_mtime_ns,
            )
            for suffix in ("", "-wal", "-shm")
        }

        materializer = SQLiteReferenceMaterializer(catalog, tmp_path / "snapshots")
        result = materializer.materialize(reference_path, source_snapshot_id)
        rerun = materializer.materialize(reference_path, source_snapshot_id)

        assert rerun == result
        assert {
            suffix: (
                Path(f"{reference_path}{suffix}").read_bytes(),
                Path(f"{reference_path}{suffix}").stat().st_mtime_ns,
            )
            for suffix in original_files
        } == original_files
        with sqlite3.connect(result.materialized_path) as materialized:
            assert materialized.execute("SELECT value FROM entries").fetchall() == [
                ("visible only through WAL",)
            ]
        derived_asset = (
            catalog.store.connection()
            .execute(
                """
            SELECT sha256, asset_version, license_id, attribution,
                   redistribution_allowed, validation_status
            FROM source_assets WHERE asset_id = ?
            """,
                [result.derived_asset_id],
            )
            .fetchone()
        )
        assert derived_asset == (
            result.materialized_sha256,
            f"2026-08+materialized.{result.materialized_sha256[:12]}",
            "CC-BY-4.0",
            "Fixture",
            True,
            ReviewState.APPROVED.value,
        )
        provenance = (
            catalog.store.connection()
            .execute(
                "SELECT payload_json FROM raw_reference_records WHERE raw_record_id = ?",
                [result.provenance_raw_record_id],
            )
            .fetchone()
        )
        assert provenance is not None
        assert '"original_asset_id":"live-wal-reference"' in provenance[0]
        assert '"original_wal_sha256":' in provenance[0]
        assert '"original_shm_sha256":' in provenance[0]
        assert (
            catalog.store.fetch_value(
                "SELECT count(*) FROM raw_reference_records "
                "WHERE record_type = 'sqlite_reference_materialization'"
            )
            == 1
        )
    finally:
        source.close()


def test_materializer_uses_source_qualified_ids_for_identical_materialized_bytes(
    catalog: SourceCatalog, wal_reference: Path, tmp_path: Path
):
    second_reference = tmp_path / "same-bytes.db"
    shutil.copyfile(wal_reference, second_reference)
    snapshot_ids: dict[str, str] = {}
    for asset_id, reference_path in (
        ("first-source", wal_reference),
        ("second-source", second_reference),
    ):
        catalog.register_source(
            SourceAssetInput(
                asset_id=asset_id,
                title=asset_id,
                locator=f"https://example.test/{asset_id}",
                asset_version="2026-08",
                sha256=SQLiteReferenceMaterializer.hash_file(reference_path),
                license_id="CC-BY-4.0",
                license_url="https://creativecommons.org/licenses/by/4.0/",
                attribution="Fixture",
                redistribution_allowed=True,
                validation_status=ReviewState.APPROVED,
            )
        )
        snapshot_ids[asset_id] = catalog.record_source_snapshot(
            asset_id, reference_path, datetime.now(UTC)
        )

    materializer = SQLiteReferenceMaterializer(catalog, tmp_path / "snapshots")
    first = materializer.materialize(wal_reference, snapshot_ids["first-source"])
    second = materializer.materialize(second_reference, snapshot_ids["second-source"])

    assert first.materialized_path == second.materialized_path
    assert first.derived_asset_id == (
        f"first-source.materialized.{first.materialized_sha256[:12]}"
    )
    assert second.derived_asset_id == (
        f"second-source.materialized.{second.materialized_sha256[:12]}"
    )
    assert first.snapshot_id != second.snapshot_id


def test_materializer_reuses_the_canonical_snapshot_path_across_output_roots(
    catalog: SourceCatalog, tmp_path: Path
):
    reference_path = tmp_path / "relocatable-reference.db"
    with sqlite3.connect(reference_path) as connection:
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
                rank INTEGER NOT NULL,
                PRIMARY KEY (word_id, sentence_id)
            );
            INSERT INTO words VALUES (1, 'book', 'noun', NULL, NULL, 1, 'A1', 'fixture');
            INSERT INTO definitions VALUES (1, 1, 'A written work.', 'sách', NULL, 'fixture');
            """)
    source = SourceAssetInput(
        asset_id="relocatable-source",
        title="Relocatable reference",
        locator="https://example.test/relocatable-reference",
        asset_version="2026-08",
        sha256=SQLiteReferenceMaterializer.hash_file(reference_path),
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution="Fixture",
        redistribution_allowed=True,
        validation_status=ReviewState.APPROVED,
    )
    catalog.register_source(source)
    source_snapshot_id = catalog.record_source_snapshot(
        source.asset_id, reference_path, datetime.now(UTC)
    )

    first = SQLiteReferenceMaterializer(catalog, tmp_path / "root-a").materialize(
        reference_path, source_snapshot_id
    )
    relocated = SQLiteReferenceMaterializer(catalog, tmp_path / "root-b").materialize(
        reference_path, source_snapshot_id
    )

    assert relocated.snapshot_id == first.snapshot_id
    assert relocated.materialized_path == first.materialized_path
    report = SQLiteLexicalReferenceImporter(catalog).import_ranked_definitions(
        relocated.materialized_path, relocated.snapshot_id, "relocated-import"
    )
    assert report.imported_or_existing_raw_records == 1


def test_materializer_rejects_a_stale_canonical_snapshot_path(
    catalog: SourceCatalog, tmp_path: Path
):
    reference_path = tmp_path / "stale-reference.db"
    with sqlite3.connect(reference_path) as connection:
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
                rank INTEGER NOT NULL,
                PRIMARY KEY (word_id, sentence_id)
            );
            INSERT INTO words VALUES (1, 'book', 'noun', NULL, NULL, 1, 'A1', 'fixture');
            INSERT INTO definitions VALUES (1, 1, 'A written work.', 'sách', NULL, 'fixture');
            """)
    source = SourceAssetInput(
        asset_id="stale-source",
        title="Stale reference",
        locator="https://example.test/stale-reference",
        asset_version="2026-08",
        sha256=SQLiteReferenceMaterializer.hash_file(reference_path),
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution="Fixture",
        redistribution_allowed=True,
        validation_status=ReviewState.APPROVED,
    )
    catalog.register_source(source)
    source_snapshot_id = catalog.record_source_snapshot(
        source.asset_id, reference_path, datetime.now(UTC)
    )
    first = SQLiteReferenceMaterializer(catalog, tmp_path / "root-a").materialize(
        reference_path, source_snapshot_id
    )
    first.materialized_path.rename(tmp_path / "archived-reference.db")

    with pytest.raises(ValueError, match="registered materialized snapshot path"):
        SQLiteReferenceMaterializer(catalog, tmp_path / "root-b").materialize(
            reference_path, source_snapshot_id
        )


def test_materializer_preserves_a_maximum_length_source_asset_id(
    catalog: SourceCatalog, wal_reference: Path, tmp_path: Path
):
    maximum_asset_id = "a" * 128
    catalog.register_source(
        SourceAssetInput(
            asset_id=maximum_asset_id,
            title="Maximum ID reference",
            locator="https://example.test/maximum-id",
            asset_version="2026-08",
            sha256=SQLiteReferenceMaterializer.hash_file(wal_reference),
            license_id="CC-BY-4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            attribution="Fixture",
            redistribution_allowed=True,
            validation_status=ReviewState.APPROVED,
        )
    )
    source_snapshot_id = catalog.record_source_snapshot(
        maximum_asset_id, wal_reference, datetime.now(UTC)
    )

    result = SQLiteReferenceMaterializer(catalog, tmp_path / "snapshots").materialize(
        wal_reference, source_snapshot_id
    )

    assert result.derived_asset_id == (
        f"{maximum_asset_id}.materialized.{result.materialized_sha256[:12]}"
    )


def test_materializer_rejects_source_ids_that_cannot_fit_an_exact_derived_id(
    catalog: SourceCatalog, wal_reference: Path, tmp_path: Path
):
    too_long_asset_id = "b" * 230
    catalog.register_source(
        SourceAssetInput(
            asset_id=too_long_asset_id,
            title="Too long ID reference",
            locator="https://example.test/too-long-id",
            asset_version="2026-08",
            sha256=SQLiteReferenceMaterializer.hash_file(wal_reference),
            license_id="CC-BY-4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            attribution="Fixture",
            redistribution_allowed=True,
            validation_status=ReviewState.APPROVED,
        )
    )
    source_snapshot_id = catalog.record_source_snapshot(
        too_long_asset_id, wal_reference, datetime.now(UTC)
    )

    with pytest.raises(ValueError, match="too long"):
        SQLiteReferenceMaterializer(catalog, tmp_path / "snapshots").materialize(
            wal_reference, source_snapshot_id
        )


def test_materializer_retries_a_wal_change_during_private_staging(
    catalog: SourceCatalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    reference_path = tmp_path / "concurrent-wal.db"
    writer = sqlite3.connect(reference_path)
    try:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        writer.execute("CREATE TABLE entries (value TEXT NOT NULL)")
        writer.commit()
        source = SourceAssetInput(
            asset_id="concurrent-wal-source",
            title="Concurrent WAL source",
            locator="https://example.test/concurrent-wal",
            asset_version="2026-08",
            sha256=SQLiteReferenceMaterializer.hash_file(reference_path),
            license_id="CC-BY-4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            attribution="Fixture",
            redistribution_allowed=True,
            validation_status=ReviewState.APPROVED,
        )
        catalog.register_source(source)
        source_snapshot_id = catalog.record_source_snapshot(
            source.asset_id, reference_path, datetime.now(UTC)
        )
        writer.execute("INSERT INTO entries VALUES ('before backup')")
        writer.commit()

        original_connect = sqlite_reference_importer.sqlite3.connect
        original_copyfile = sqlite_reference_importer.shutil.copyfile
        source_uri = f"{reference_path.resolve().as_uri()}?mode=ro"
        source_wal_path = Path(f"{reference_path}-wal")
        wal_copy_attempts = 0

        def forbid_opening_the_original_source(
            database: str | Path, *args: object, **kwargs: object
        ) -> sqlite3.Connection:
            if database == source_uri:
                raise AssertionError("materializer must not open the original SQLite")
            return original_connect(database, *args, **kwargs)

        def mutate_after_first_wal_copy(
            source: str | Path, destination: str | Path
        ) -> str:
            nonlocal wal_copy_attempts
            copied = original_copyfile(source, destination)
            if Path(source) == source_wal_path:
                wal_copy_attempts += 1
                if wal_copy_attempts == 1:
                    with original_connect(reference_path) as concurrent_writer:
                        concurrent_writer.execute(
                            "INSERT INTO entries VALUES ('during private staging')"
                        )
            return copied

        monkeypatch.setattr(
            sqlite_reference_importer.sqlite3,
            "connect",
            forbid_opening_the_original_source,
        )
        monkeypatch.setattr(
            sqlite_reference_importer.shutil,
            "copyfile",
            mutate_after_first_wal_copy,
        )

        result = SQLiteReferenceMaterializer(
            catalog, tmp_path / "snapshots"
        ).materialize(reference_path, source_snapshot_id)

        with sqlite3.connect(result.materialized_path) as materialized:
            assert materialized.execute(
                "SELECT value FROM entries ORDER BY rowid"
            ).fetchall() == [
                ("before backup",),
                ("during private staging",),
            ]
        assert wal_copy_attempts == 2
    finally:
        writer.close()


def test_materializer_rejects_an_unreadable_existing_wal(
    catalog: SourceCatalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    reference_path = tmp_path / "unreadable-wal.db"
    writer = sqlite3.connect(reference_path)
    try:
        assert writer.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)
        writer.execute("CREATE TABLE entries (value TEXT NOT NULL)")
        writer.commit()
        source = SourceAssetInput(
            asset_id="unreadable-wal-source",
            title="Unreadable WAL source",
            locator="https://example.test/unreadable-wal",
            asset_version="2026-08",
            sha256=SQLiteReferenceMaterializer.hash_file(reference_path),
            license_id="CC-BY-4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            attribution="Fixture",
            redistribution_allowed=True,
            validation_status=ReviewState.APPROVED,
        )
        catalog.register_source(source)
        source_snapshot_id = catalog.record_source_snapshot(
            source.asset_id, reference_path, datetime.now(UTC)
        )
        writer.execute("INSERT INTO entries VALUES ('requires the WAL')")
        writer.commit()
        wal_path = Path(f"{reference_path}-wal")
        original_hash_file = SQLiteReferenceMaterializer.hash_file

        def fail_to_hash_wal(path: Path) -> str:
            if Path(path) == wal_path:
                raise OSError("WAL is unreadable")
            return original_hash_file(path)

        monkeypatch.setattr(
            SQLiteReferenceMaterializer,
            "hash_file",
            staticmethod(fail_to_hash_wal),
        )

        with pytest.raises(OSError, match="unreadable"):
            SQLiteReferenceMaterializer(catalog, tmp_path / "snapshots").materialize(
                reference_path, source_snapshot_id
            )
    finally:
        writer.close()
