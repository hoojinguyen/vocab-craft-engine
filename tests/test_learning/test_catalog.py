import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Lock, Thread
from typing import Any

import duckdb
import pytest

from src.learning import schema
from src.learning.catalog import RawRecordInput, SourceCatalog, SourceEvidenceLinkInput
from src.learning.models import ReviewState, SourceAssetInput, canonical_json
from src.learning.store import LearningGraphStore


def _approved_source(asset_id: str = "approved-source") -> SourceAssetInput:
    return SourceAssetInput(
        asset_id=asset_id,
        title="Approved source",
        locator="https://example.test/sources/approved",
        asset_version="2026-08",
        sha256="a" * 64,
        license_id="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        attribution="Example author",
        redistribution_allowed=True,
        validation_status=ReviewState.APPROVED,
    )


@pytest.fixture
def catalog(tmp_path: Path) -> SourceCatalog:
    store = LearningGraphStore(tmp_path / "graph.duckdb")
    store.initialize()
    return SourceCatalog(store)


class _FirstStatementsGate:
    def __init__(self, readers: int):
        self._barrier = Barrier(readers)
        self._lock = Lock()
        self._remaining = readers

    def wait(self) -> None:
        with self._lock:
            if self._remaining == 0:
                return
            self._remaining -= 1
        self._barrier.wait(timeout=5)


class _ReadSynchronizingConnection:
    def __init__(self, connection: Any, sql_prefix: str, gate: _FirstStatementsGate):
        self._connection = connection
        self._sql_prefix = sql_prefix
        self._gate = gate

    def execute(self, sql: str, params: Any = None) -> Any:
        result = self._connection.execute(sql, params)
        if " ".join(sql.split()).startswith(self._sql_prefix):
            self._gate.wait()
        return result


def _synchronize_first_matching_statements(
    monkeypatch: pytest.MonkeyPatch,
    catalog: SourceCatalog,
    sql_prefix: str,
    gate: _FirstStatementsGate,
) -> None:
    transaction = catalog.store.transaction

    @contextmanager
    def synchronized_transaction() -> Iterator[_ReadSynchronizingConnection]:
        with transaction() as connection:
            yield _ReadSynchronizingConnection(connection, sql_prefix, gate)

    monkeypatch.setattr(catalog.store, "transaction", synchronized_transaction)


def _run_concurrently(
    first: Callable[[], Any], second: Callable[[], Any]
) -> tuple[list[Any], list[Exception]]:
    results: list[Any] = []
    errors: list[Exception] = []
    lock = Lock()

    def run(operation: Callable[[], Any]) -> None:
        try:
            result = operation()
        except (ValueError, duckdb.Error) as exc:
            with lock:
                errors.append(exc)
        else:
            with lock:
                results.append(result)

    workers = [Thread(target=run, args=(operation,)) for operation in (first, second)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    assert all(not worker.is_alive() for worker in workers)
    return results, errors


def _catalogs(tmp_path: Path) -> tuple[SourceCatalog, SourceCatalog]:
    db_path = tmp_path / "graph.duckdb"
    first_store = LearningGraphStore(db_path)
    second_store = LearningGraphStore(db_path)
    first_store.initialize()
    second_store.initialize()
    return SourceCatalog(first_store), SourceCatalog(second_store)


def test_register_source_is_idempotent_and_preserves_input_attributes(
    catalog: SourceCatalog,
):
    source = _approved_source()

    catalog.register_source(source)
    catalog.register_source(
        source.model_copy(
            update={
                "title": "Replacement title",
                "attribution": "Replacement attribution",
                "validation_status": ReviewState.CANDIDATE,
            }
        )
    )

    assert (
        catalog.store.connection()
        .execute(
            """
        SELECT title, locator, asset_version, sha256, license_id, license_url,
               attribution, redistribution_allowed, validation_status
        FROM source_assets WHERE asset_id = ?
        """,
            [source.asset_id],
        )
        .fetchall()
        == [
            (
                source.title,
                str(source.locator),
                source.asset_version,
                source.sha256,
                source.license_id,
                str(source.license_url),
                source.attribution,
                True,
                ReviewState.APPROVED.value,
            )
        ]
    )


def test_register_source_rejects_changed_checksum(catalog: SourceCatalog):
    catalog.register_source(_approved_source())
    changed = _approved_source().model_copy(update={"sha256": "b" * 64})

    with pytest.raises(ValueError, match="checksum"):
        catalog.register_source(changed)

    assert (
        catalog.store.fetch_value(
            "SELECT sha256 FROM source_assets WHERE asset_id = ?", [changed.asset_id]
        )
        == "a" * 64
    )


def test_record_source_snapshot_persists_checksum_and_is_idempotent(
    catalog: SourceCatalog, tmp_path: Path
):
    source_file = tmp_path / "reference.db"
    contents = b"reference snapshot"
    source_file.write_bytes(contents)
    checksum = hashlib.sha256(contents).hexdigest()
    source = _approved_source().model_copy(update={"sha256": checksum})
    catalog.register_source(source)
    retrieved_at = datetime(2026, 8, 17, 7, 0, tzinfo=timezone(timedelta(hours=7)))

    first_snapshot_id = catalog.record_source_snapshot(
        source.asset_id, source_file, retrieved_at
    )
    second_snapshot_id = catalog.record_source_snapshot(
        source.asset_id, source_file, retrieved_at
    )

    assert second_snapshot_id == first_snapshot_id
    assert source_file.read_bytes() == contents
    assert catalog.store.connection().execute(
        "SELECT asset_id, local_path, retrieved_at, file_sha256 "
        "FROM source_snapshots WHERE snapshot_id = ?",
        [first_snapshot_id],
    ).fetchone() == (
        source.asset_id,
        str(source_file),
        datetime.fromisoformat("2026-08-17T00:00:00"),
        checksum,
    )


def test_record_source_snapshot_rejects_unregistered_or_mismatched_files(
    catalog: SourceCatalog, tmp_path: Path
):
    source_file = tmp_path / "reference.db"
    source_file.write_bytes(b"reference snapshot")
    catalog.register_source(_approved_source())

    with pytest.raises(ValueError, match="checksum"):
        catalog.record_source_snapshot(
            "approved-source", source_file, datetime(2026, 8, 17, tzinfo=UTC)
        )

    with pytest.raises(ValueError, match="registered"):
        catalog.record_source_snapshot(
            "missing-source", source_file, datetime(2026, 8, 17, tzinfo=UTC)
        )

    assert catalog.store.fetch_value("SELECT count(*) FROM source_snapshots") == 0


@pytest.mark.parametrize("frequency_rank", [0, -1, 3501])
def test_lexical_definition_records_reject_out_of_scope_frequency_ranks(
    catalog: SourceCatalog, tmp_path: Path, frequency_rank: int
):
    source_file = tmp_path / "reference.db"
    source_file.write_bytes(b"verified materialized database")
    source = _approved_source().model_copy(
        update={"sha256": hashlib.sha256(source_file.read_bytes()).hexdigest()}
    )
    catalog.register_source(source)
    snapshot_id = catalog.record_source_snapshot(
        source.asset_id, source_file, datetime(2026, 8, 18, tzinfo=UTC)
    )
    record = RawRecordInput(
        asset_id=source.asset_id,
        external_key=f"sqlite-lexical-definition:1:{frequency_rank}",
        record_type="sqlite_lexical_definition_evidence",
        payload={
            "word": {
                "source_row_id": 1,
                "lemma": "book",
                "pos": "noun",
                "frequency_rank": frequency_rank,
            },
            "definition": {"source_row_id": 1, "source": "fixture"},
            "definitions": [{"source_row_id": 1, "source": "fixture"}],
            "translations": [],
            "examples": [],
        },
        import_run_id="invalid-rank",
    )

    with pytest.raises(ValueError, match="frequency rank"):
        catalog.append_lexical_definition_record(record, snapshot_id)

    assert catalog.store.fetch_value("SELECT count(*) FROM raw_reference_records") == 0
    assert (
        catalog.store.fetch_value("SELECT count(*) FROM lexical_definition_inputs") == 0
    )


def test_migration_v6_rekeys_a_v5_lexical_input_for_idempotent_reappend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    all_migrations = schema.MIGRATIONS
    monkeypatch.setattr(
        schema,
        "MIGRATIONS",
        [migration for migration in all_migrations if migration[0] <= 5],
    )
    store = LearningGraphStore(tmp_path / "v5-graph.duckdb")
    store.initialize()
    catalog = SourceCatalog(store)
    reference_path = tmp_path / "materialized-reference.db"
    reference_path.write_bytes(b"verified materialized database")
    source = _approved_source().model_copy(
        update={"sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest()}
    )
    catalog.register_source(source)
    snapshot_id = catalog.record_source_snapshot(
        source.asset_id, reference_path, datetime(2026, 8, 18, tzinfo=UTC)
    )
    record = RawRecordInput(
        asset_id=source.asset_id,
        external_key="sqlite-lexical-definition:10:11",
        record_type="sqlite_lexical_definition_evidence",
        payload={
            "word": {
                "source_row_id": 10,
                "lemma": "book",
                "pos": "noun",
                "frequency_rank": 100,
            },
            "definition": {
                "source_row_id": 11,
                "definition_en": "A written work.",
                "source": "fixture",
            },
            "definitions": [
                {
                    "source_row_id": 11,
                    "definition_en": "A written work.",
                    "source": "fixture",
                }
            ],
            "translations": [],
            "examples": [],
        },
        import_run_id="legacy-import",
    )
    raw_record_id = catalog.append_raw_record(
        record.asset_id,
        record.external_key,
        record.record_type,
        record.payload,
        record.import_run_id,
    )
    definition = record.payload["definition"]
    definition_sha256 = hashlib.sha256(
        canonical_json(definition).encode("utf-8")
    ).hexdigest()
    connection = store.connection()
    connection.execute(
        """
        INSERT INTO lexical_definition_inputs (
            input_id, snapshot_id, raw_record_id, source_word_id,
            source_definition_id, input_key, source_definition_sha256, lemma,
            pos, frequency_rank
        ) VALUES ('legacy-input', ?, ?, 10, 11, ?, ?, 'book', 'noun', 100)
        """,
        [snapshot_id, raw_record_id, record.external_key, definition_sha256],
    )
    connection.execute(
        """
        INSERT INTO lexical_evidence_items (
            evidence_id, input_id, evidence_role, source_row_id, source_name,
            value_json, value_sha256
        ) VALUES ('legacy-evidence', 'legacy-input', 'definition', 11, 'fixture', ?, ?)
        """,
        [canonical_json(definition), definition_sha256],
    )

    monkeypatch.setattr(schema, "MIGRATIONS", all_migrations)
    store.initialize()

    assert (
        catalog.append_lexical_definition_record(record, snapshot_id) == raw_record_id
    )
    assert catalog.store.fetch_value("SELECT count(*) FROM raw_reference_records") == 1
    assert (
        catalog.store.fetch_value("SELECT count(*) FROM lexical_definition_inputs") == 1
    )
    assert catalog.store.fetch_value("SELECT count(*) FROM lexical_evidence_items") == 1
    assert (
        catalog.store.fetch_value("SELECT input_key FROM lexical_definition_inputs")
        == f"{source.asset_id}:{snapshot_id}:{record.external_key}"
    )


def test_register_source_propagates_invalid_source_constraint(catalog: SourceCatalog):
    invalid = _approved_source().model_copy(update={"title": None})

    with pytest.raises(duckdb.ConstraintException, match="NOT NULL"):
        catalog.register_source(invalid)


def test_concurrent_source_registration_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    first_catalog, second_catalog = _catalogs(tmp_path)
    read_gate = _FirstStatementsGate(readers=2)
    write_gate = _FirstStatementsGate(readers=2)
    for catalog in (first_catalog, second_catalog):
        _synchronize_first_matching_statements(
            monkeypatch,
            catalog,
            "SELECT sha256 FROM source_assets",
            read_gate,
        )
        _synchronize_first_matching_statements(
            monkeypatch,
            catalog,
            "INSERT INTO source_assets",
            write_gate,
        )

    results, errors = _run_concurrently(
        lambda: first_catalog.register_source(_approved_source()),
        lambda: second_catalog.register_source(_approved_source()),
    )

    assert results == [None, None]
    assert errors == []
    assert (
        first_catalog.store.fetch_value(
            "SELECT count(*) FROM source_assets WHERE asset_id = ?", ["approved-source"]
        )
        == 1
    )


def test_concurrent_source_registration_with_changed_checksum_raises_value_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    first_catalog, second_catalog = _catalogs(tmp_path)
    read_gate = _FirstStatementsGate(readers=2)
    write_gate = _FirstStatementsGate(readers=2)
    for catalog in (first_catalog, second_catalog):
        _synchronize_first_matching_statements(
            monkeypatch,
            catalog,
            "SELECT sha256 FROM source_assets",
            read_gate,
        )
        _synchronize_first_matching_statements(
            monkeypatch,
            catalog,
            "INSERT INTO source_assets",
            write_gate,
        )

    results, errors = _run_concurrently(
        lambda: first_catalog.register_source(_approved_source()),
        lambda: second_catalog.register_source(
            _approved_source().model_copy(update={"sha256": "b" * 64})
        ),
    )

    assert results == [None]
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert "different checksum" in str(errors[0])
    assert (
        first_catalog.store.fetch_value(
            "SELECT count(*) FROM source_assets WHERE asset_id = ?", ["approved-source"]
        )
        == 1
    )


@pytest.mark.parametrize(
    "asset_id, registered", [("missing-source", False), ("pending-source", True)]
)
def test_record_raw_snapshot_requires_an_approved_source(
    catalog: SourceCatalog, asset_id: str, registered: bool
):
    if registered:
        catalog.register_source(
            _approved_source(asset_id).model_copy(
                update={"validation_status": ReviewState.CANDIDATE}
            )
        )

    with pytest.raises(ValueError, match="approved"):
        catalog.record_raw_snapshot(asset_id, "word:hello", {"word": "hello"})

    assert catalog.store.fetch_value("SELECT count(*) FROM raw_reference_records") == 0


def test_record_raw_snapshot_is_idempotent_for_canonical_payload(
    catalog: SourceCatalog,
):
    source = _approved_source()
    catalog.register_source(source)

    first_id = catalog.record_raw_snapshot(
        source.asset_id, "word:hello", {"word": "hello", "rank": 1}
    )
    second_id = catalog.record_raw_snapshot(
        source.asset_id, "word:hello", {"rank": 1, "word": "hello"}
    )
    expected_payload = canonical_json({"rank": 1, "word": "hello"})

    assert second_id == first_id
    assert (
        catalog.store.connection()
        .execute(
            """
        SELECT raw_record_id, payload_json, payload_sha256
        FROM raw_reference_records
        WHERE asset_id = ? AND external_key = ?
        """,
            [source.asset_id, "word:hello"],
        )
        .fetchall()
        == [
            (
                first_id,
                expected_payload,
                hashlib.sha256(expected_payload.encode("utf-8")).hexdigest(),
            )
        ]
    )


def test_record_raw_snapshot_retains_changed_payload_as_second_record(
    catalog: SourceCatalog,
):
    source = _approved_source()
    catalog.register_source(source)

    first_id = catalog.record_raw_snapshot(
        source.asset_id, "word:hello", {"word": "hello", "rank": 1}
    )
    second_id = catalog.record_raw_snapshot(
        source.asset_id, "word:hello", {"word": "hello", "rank": 2}
    )

    assert first_id != second_id
    rows = (
        catalog.store.connection()
        .execute(
            """
        SELECT raw_record_id, payload_sha256
        FROM raw_reference_records
        WHERE asset_id = ? AND external_key = ?
        ORDER BY payload_sha256
        """,
            [source.asset_id, "word:hello"],
        )
        .fetchall()
    )
    assert len(rows) == 2
    assert {row[0] for row in rows} == {first_id, second_id}
    assert {row[1] for row in rows} == {
        hashlib.sha256(
            canonical_json({"word": "hello", "rank": 1}).encode("utf-8")
        ).hexdigest(),
        hashlib.sha256(
            canonical_json({"word": "hello", "rank": 2}).encode("utf-8")
        ).hexdigest(),
    }


def test_concurrent_raw_snapshot_recording_returns_one_record_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    first_catalog, second_catalog = _catalogs(tmp_path)
    source = _approved_source()
    first_catalog.register_source(source)
    read_gate = _FirstStatementsGate(readers=2)
    write_gate = _FirstStatementsGate(readers=2)
    for catalog in (first_catalog, second_catalog):
        _synchronize_first_matching_statements(
            monkeypatch,
            catalog,
            "SELECT raw_record_id FROM raw_reference_records",
            read_gate,
        )
        _synchronize_first_matching_statements(
            monkeypatch,
            catalog,
            "INSERT INTO raw_reference_records",
            write_gate,
        )

    results, errors = _run_concurrently(
        lambda: first_catalog.record_raw_snapshot(
            source.asset_id, "word:hello", {"word": "hello"}
        ),
        lambda: second_catalog.record_raw_snapshot(
            source.asset_id, "word:hello", {"word": "hello"}
        ),
    )

    assert errors == []
    assert len(results) == 2
    assert results[0] == results[1]
    assert (
        first_catalog.store.connection()
        .execute(
            """
        SELECT raw_record_id FROM raw_reference_records
        WHERE asset_id = ? AND external_key = ?
        """,
            [source.asset_id, "word:hello"],
        )
        .fetchall()
        == [(results[0],)]
    )


def test_append_source_evidence_links_deduplicates_sentence_value_and_word_link(
    catalog: SourceCatalog, tmp_path: Path
):
    source_file = tmp_path / "materialized.db"
    source_file.write_bytes(b"materialized SQLite")
    source = _approved_source().model_copy(
        update={"sha256": hashlib.sha256(source_file.read_bytes()).hexdigest()}
    )
    catalog.register_source(source)
    snapshot_id = catalog.record_source_snapshot(
        source.asset_id, source_file, datetime(2026, 8, 18, tzinfo=UTC)
    )
    link = SourceEvidenceLinkInput(
        snapshot_id=snapshot_id,
        source_word_id=10,
        source_row_id=30,
        source_name="tatoeba",
        source_table="sentences",
        link_rank=2,
        value={
            "sentence_id": 30,
            "text_en": "Read this book.",
            "text_vi": "Hãy đọc quyển sách này.",
            "source": "tatoeba",
        },
    )

    first_ids = catalog.append_source_example_links([link])
    second_ids = catalog.append_source_example_links([link])

    assert second_ids == first_ids
    assert (
        catalog.store.fetch_value("SELECT count(*) FROM lexical_source_evidence") == 1
    )
    assert (
        catalog.store.fetch_value("SELECT count(*) FROM lexical_word_evidence_links")
        == 1
    )


def test_append_source_evidence_links_uses_set_oriented_writes_for_a_batch(
    catalog: SourceCatalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A full corpus import must not issue two SQL statements per sentence link."""
    source_file = tmp_path / "materialized.db"
    source_file.write_bytes(b"materialized SQLite")
    source = _approved_source().model_copy(
        update={"sha256": hashlib.sha256(source_file.read_bytes()).hexdigest()}
    )
    catalog.register_source(source)
    snapshot_id = catalog.record_source_snapshot(
        source.asset_id, source_file, datetime(2026, 8, 18, tzinfo=UTC)
    )
    link_insert_calls: list[str] = []
    transaction = catalog.store.transaction

    class RecordingConnection:
        def __init__(self, connection: Any):
            self._connection = connection

        def execute(self, sql: str, params: Any = None) -> Any:
            normalized_sql = " ".join(sql.split())
            if (
                "INSERT INTO lexical_source_evidence" in normalized_sql
                or "INSERT INTO lexical_word_evidence_links" in normalized_sql
            ):
                link_insert_calls.append(normalized_sql)
            return self._connection.execute(sql, params)

    @contextmanager
    def recording_transaction() -> Iterator[RecordingConnection]:
        with transaction() as connection:
            yield RecordingConnection(connection)

    monkeypatch.setattr(catalog.store, "transaction", recording_transaction)
    links = [
        SourceEvidenceLinkInput(
            snapshot_id=snapshot_id,
            source_word_id=10,
            source_row_id=index,
            source_name="tatoeba",
            source_table="sentences",
            link_rank=index,
            value={
                "kind": "linked",
                "sentence_id": index,
                "text_en": f"Sentence {index}.",
                "text_vi": f"Câu {index}.",
                "source": "tatoeba",
            },
        )
        for index in range(1, 251)
    ]

    catalog.append_source_example_links(links)

    assert len(link_insert_calls) == 2
    assert (
        catalog.store.fetch_value("SELECT count(*) FROM lexical_source_evidence") == 250
    )
    assert (
        catalog.store.fetch_value("SELECT count(*) FROM lexical_word_evidence_links")
        == 250
    )


@pytest.mark.parametrize("source_word_id,source_row_id", [(0, 30), (10, -1)])
def test_append_source_evidence_links_rejects_non_positive_source_ids(
    catalog: SourceCatalog, tmp_path: Path, source_word_id: int, source_row_id: int
):
    source_file = tmp_path / "materialized.db"
    source_file.write_bytes(b"materialized SQLite")
    source = _approved_source().model_copy(
        update={"sha256": hashlib.sha256(source_file.read_bytes()).hexdigest()}
    )
    catalog.register_source(source)
    snapshot_id = catalog.record_source_snapshot(
        source.asset_id, source_file, datetime(2026, 8, 18, tzinfo=UTC)
    )

    with pytest.raises(ValueError, match="positive"):
        catalog.append_source_example_links(
            [
                SourceEvidenceLinkInput(
                    snapshot_id=snapshot_id,
                    source_word_id=source_word_id,
                    source_row_id=source_row_id,
                    source_name="tatoeba",
                    source_table="sentences",
                    link_rank=1,
                    value={"text_en": "Read.", "text_vi": "Đọc."},
                )
            ]
        )
