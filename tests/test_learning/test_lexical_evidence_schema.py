from pathlib import Path

import duckdb
import pytest

from src.learning.schema import GRAPH_TABLES, MIGRATIONS, apply_migrations
from src.learning.store import LearningGraphStore

LEXICAL_TABLES = {
    "lexical_definition_inputs",
    "lexical_evidence_items",
    "lexical_evidence_rankings",
    "lexical_input_canonical_map",
    "lexical_input_dispositions",
    "lexical_remediation_attempts",
    "lexical_quarantine_cases",
    "lexical_run_checkpoints",
    "lexical_release_builds",
}


def _seed_dependencies(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        """
        INSERT INTO source_assets VALUES
        ('source-1', 'Source', 'https://example.test/source', '1', ?,
         'CC-BY-4.0', 'https://example.test/license', 'Fixture', TRUE,
         'approved', current_timestamp)
        """,
        ["a" * 64],
    )
    conn.execute(
        """
        INSERT INTO raw_reference_records VALUES
        ('raw-1', 'source-1', 'external-1', 'sqlite_lexical_bundle', '{}', ?,
         'import-1', current_timestamp)
        """,
        ["b" * 64],
    )
    conn.execute(
        """
        INSERT INTO source_snapshots VALUES
        ('snapshot-1', 'source-1', '/tmp/reference.db', current_timestamp, ?,
         current_timestamp)
        """,
        ["c" * 64],
    )
    conn.execute("""
        INSERT INTO validation_runs VALUES
        ('run-1', 'snapshot-1', 'lexical-v1', '{}', current_timestamp, NULL)
        """)
    conn.execute("""
        INSERT INTO content_candidates VALUES
        ('candidate-1', 'raw-1', 'sense', '{}', '{}', 1.0, 'validated',
         current_timestamp)
        """)


def _insert_input(conn: duckdb.DuckDBPyConnection, input_id: str = "input-1") -> None:
    conn.execute(
        """
        INSERT INTO lexical_definition_inputs (
            input_id, snapshot_id, raw_record_id, source_word_id,
            source_definition_id, input_key, source_definition_sha256, lemma,
            pos, frequency_rank
        ) VALUES (?, 'snapshot-1', 'raw-1', 10, 11, ?, ?, 'book', 'noun', 42)
        """,
        [input_id, f"lexical.book.noun.{input_id}", "d" * 64],
    )


def _insert_evidence(
    conn: duckdb.DuckDBPyConnection, evidence_id: str = "evidence-1"
) -> None:
    conn.execute(
        """
        INSERT INTO lexical_evidence_items (
            evidence_id, input_id, evidence_role, source_row_id, source_name,
            value_json, value_sha256
        ) VALUES (?, 'input-1', 'definition', 101, 'reference.db', ?, ?)
        """,
        [evidence_id, '{"text":"a set of pages"}', "e" * 64],
    )


def _insert_lexical_dependents(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        INSERT INTO lexical_evidence_rankings VALUES
        ('run-1', 'input-1', 'evidence-1', 'definition', 1, TRUE, TRUE, '{}')
        """)
    conn.execute("""
        INSERT INTO lexical_input_canonical_map VALUES
        ('input-1', 'sense.book.noun', 'candidate-1', current_timestamp)
        """)
    conn.execute("""
        INSERT INTO lexical_input_dispositions VALUES
        ('run-1', 'input-1', 'validated', 'candidate-1', '[]', '{}', current_timestamp)
        """)
    conn.execute("""
        INSERT INTO lexical_remediation_attempts VALUES
        ('attempt-1', 'run-1', 'input-1', 1, '{}', 'validated', '[]', '{}', current_timestamp)
        """)
    conn.execute("""
        INSERT INTO lexical_quarantine_cases VALUES
        ('case-1', 'input-1', 'run-1', 'resolved', 0, '[]', '[]', current_timestamp)
        """)
    conn.execute("""
        INSERT INTO lexical_run_checkpoints VALUES
        ('run-1', 'evidence_ranked', 'lexical.book.noun.input-1', 1, current_timestamp, current_timestamp)
        """)
    conn.execute(
        """
        INSERT INTO lexical_release_builds VALUES
        ('build-1', 'run-1', '2026.08.18', ?, '{}', '/tmp/lexical.db', current_timestamp)
        """,
        ["f" * 64],
    )


def test_fresh_v6_graph_persists_the_lexical_evidence_graph():
    conn = duckdb.connect(":memory:")
    apply_migrations(conn)

    assert MIGRATIONS[-1][0] == 6
    assert LEXICAL_TABLES.issubset(GRAPH_TABLES)
    assert conn.execute(
        "SELECT version FROM graph_schema_migrations ORDER BY version"
    ).fetchall() == [(1,), (2,), (3,), (4,), (5,), (6,)]
    assert {
        row[1]
        for row in conn.execute(
            "PRAGMA table_info('lexical_definition_inputs')"
        ).fetchall()
    } >= {
        "input_id",
        "snapshot_id",
        "raw_record_id",
        "source_word_id",
        "source_definition_id",
        "input_key",
        "source_definition_sha256",
        "lemma",
        "pos",
        "frequency_rank",
        "created_at",
    }

    _seed_dependencies(conn)
    _insert_input(conn)
    _insert_evidence(conn)
    _insert_lexical_dependents(conn)

    assert conn.execute("""
        SELECT input.lemma, evidence.evidence_role, disposition.state, build.release_version
        FROM lexical_definition_inputs AS input
        JOIN lexical_evidence_items AS evidence ON evidence.input_id = input.input_id
        JOIN lexical_input_dispositions AS disposition ON disposition.input_id = input.input_id
        JOIN lexical_release_builds AS build ON build.validation_run_id = disposition.validation_run_id
        """).fetchall() == [("book", "definition", "validated", "2026.08.18")]


def test_migration_v5_to_v6_preserves_inputs_and_enforces_frozen_rank(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = duckdb.connect(":memory:")
    all_migrations = MIGRATIONS
    v5_migrations = [migration for migration in all_migrations if migration[0] <= 5]
    monkeypatch.setattr("src.learning.schema.MIGRATIONS", v5_migrations)
    apply_migrations(conn)
    _seed_dependencies(conn)
    _insert_input(conn)
    _insert_evidence(conn)
    _insert_lexical_dependents(conn)

    monkeypatch.setattr("src.learning.schema.MIGRATIONS", all_migrations)
    apply_migrations(conn)

    assert conn.execute(
        "SELECT asset_id, external_key FROM raw_reference_records"
    ).fetchall() == [("source-1", "external-1")]
    assert conn.execute(
        "SELECT snapshot_id, policy_version FROM validation_runs"
    ).fetchall() == [("snapshot-1", "lexical-v1")]
    assert conn.execute(
        "SELECT version FROM graph_schema_migrations ORDER BY version"
    ).fetchall() == [(1,), (2,), (3,), (4,), (5,), (6,)]
    assert conn.execute(
        "SELECT input_key FROM lexical_definition_inputs"
    ).fetchall() == [("source-1:snapshot-1:external-1",)]
    assert conn.execute(
        "SELECT evidence_id FROM lexical_evidence_items"
    ).fetchall() == [("evidence-1",)]
    assert conn.execute(
        "SELECT last_input_key FROM lexical_run_checkpoints"
    ).fetchall() == [("source-1:snapshot-1:external-1",)]
    assert {
        table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in LEXICAL_TABLES
    } == {table: 1 for table in LEXICAL_TABLES}
    with pytest.raises(duckdb.ConstraintException):
        conn.execute(
            """
            INSERT INTO lexical_definition_inputs (
                input_id, snapshot_id, raw_record_id, source_word_id,
                source_definition_id, input_key, source_definition_sha256, lemma,
                pos, frequency_rank
            ) VALUES ('invalid-v6-rank', 'snapshot-1', 'raw-1', 10, 12,
                      'lexical.book.noun.invalid-v6-rank', ?, 'book', 'noun', 0)
            """,
            ["d" * 64],
        )


def test_migration_v6_rejects_colliding_rekeyed_input_identities(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = duckdb.connect(":memory:")
    all_migrations = MIGRATIONS
    v5_migrations = [migration for migration in all_migrations if migration[0] <= 5]
    monkeypatch.setattr("src.learning.schema.MIGRATIONS", v5_migrations)
    apply_migrations(conn)
    _seed_dependencies(conn)
    _insert_input(conn)
    conn.execute(
        """
        INSERT INTO raw_reference_records VALUES
        ('raw-2', 'source-1', 'external-1', 'sqlite_lexical_definition_evidence',
         '{"definition":2}', ?, 'import-2', current_timestamp)
        """,
        ["f" * 64],
    )
    conn.execute(
        """
        INSERT INTO lexical_definition_inputs (
            input_id, snapshot_id, raw_record_id, source_word_id,
            source_definition_id, input_key, source_definition_sha256, lemma,
            pos, frequency_rank
        ) VALUES ('input-2', 'snapshot-1', 'raw-2', 10, 12, 'legacy-input-2', ?,
                  'book', 'noun', 42)
        """,
        ["e" * 64],
    )

    monkeypatch.setattr("src.learning.schema.MIGRATIONS", all_migrations)

    with pytest.raises(ValueError, match="rekey.*collision"):
        apply_migrations(conn)

    assert conn.execute(
        "SELECT version FROM graph_schema_migrations ORDER BY version"
    ).fetchall() == [(1,), (2,), (3,), (4,), (5,)]


def test_migration_v6_rejects_input_with_mismatched_raw_asset_lineage(
    monkeypatch: pytest.MonkeyPatch,
):
    conn = duckdb.connect(":memory:")
    all_migrations = MIGRATIONS
    v5_migrations = [migration for migration in all_migrations if migration[0] <= 5]
    monkeypatch.setattr("src.learning.schema.MIGRATIONS", v5_migrations)
    apply_migrations(conn)
    _seed_dependencies(conn)
    conn.execute(
        """
        INSERT INTO source_assets VALUES
        ('source-2', 'Other Source', 'https://example.test/other', '1', ?,
         'CC-BY-4.0', 'https://example.test/license', 'Fixture', TRUE,
         'approved', current_timestamp)
        """,
        ["d" * 64],
    )
    conn.execute(
        """
        INSERT INTO raw_reference_records VALUES
        ('raw-2', 'source-2', 'external-2', 'sqlite_lexical_definition_evidence',
         '{"definition":2}', ?, 'import-2', current_timestamp)
        """,
        ["f" * 64],
    )
    conn.execute(
        """
        INSERT INTO lexical_definition_inputs (
            input_id, snapshot_id, raw_record_id, source_word_id,
            source_definition_id, input_key, source_definition_sha256, lemma,
            pos, frequency_rank
        ) VALUES ('input-2', 'snapshot-1', 'raw-2', 10, 12, 'legacy-input-2', ?,
                  'book', 'noun', 42)
        """,
        ["e" * 64],
    )

    monkeypatch.setattr("src.learning.schema.MIGRATIONS", all_migrations)

    with pytest.raises(ValueError, match="source lineage"):
        apply_migrations(conn)


def test_lexical_evidence_tables_enforce_foreign_key_relationships():
    conn = duckdb.connect(":memory:")
    apply_migrations(conn)
    _seed_dependencies(conn)
    _insert_input(conn)
    _insert_evidence(conn)

    with pytest.raises(duckdb.ConstraintException):
        conn.execute(
            """
            INSERT INTO lexical_definition_inputs (
                input_id, snapshot_id, raw_record_id, input_key,
                source_definition_sha256, lemma, pos, frequency_rank
            ) VALUES ('missing-raw', 'snapshot-1', 'missing-raw', 'missing.raw', ?, 'missing', 'noun', 1)
            """,
            ["0" * 64],
        )
    with pytest.raises(duckdb.ConstraintException):
        conn.execute(
            """
            INSERT INTO lexical_evidence_items VALUES
            ('missing-input', 'missing-input', 'definition', 1, 'source', '{}', ?,
             current_timestamp)
            """,
            ["0" * 64],
        )
    with pytest.raises(duckdb.ConstraintException):
        conn.execute("""
            INSERT INTO lexical_evidence_rankings VALUES
            ('run-1', 'input-1', 'missing-evidence', 'definition', 1, TRUE, TRUE, '{}')
            """)
    with pytest.raises(duckdb.ConstraintException):
        conn.execute("""
            INSERT INTO lexical_input_canonical_map VALUES
            ('input-1', 'sense.book.noun', 'missing-candidate', current_timestamp)
            """)
    with pytest.raises(duckdb.ConstraintException):
        conn.execute("""
            INSERT INTO lexical_input_dispositions VALUES
            ('missing-run', 'input-1', 'validated', NULL, '[]', '{}', current_timestamp)
            """)
    with pytest.raises(duckdb.ConstraintException):
        conn.execute("""
            INSERT INTO lexical_remediation_attempts VALUES
            ('missing-run', 'missing-run', 'input-1', 1, '{}', 'validated', '[]', '{}', current_timestamp)
            """)
    with pytest.raises(duckdb.ConstraintException):
        conn.execute("""
            INSERT INTO lexical_quarantine_cases VALUES
            ('missing-input-case', 'missing-input', 'run-1', 'open', 0, '[]', '[]', current_timestamp)
            """)
    with pytest.raises(duckdb.ConstraintException):
        conn.execute("""
            INSERT INTO lexical_run_checkpoints VALUES
            ('missing-run', 'ingest', NULL, 0, NULL, current_timestamp)
            """)
    with pytest.raises(duckdb.ConstraintException):
        conn.execute(
            """
            INSERT INTO lexical_release_builds VALUES
            ('missing-run-build', 'missing-run', '0.0.0', ?, '{}', '/tmp/none', current_timestamp)
            """,
            ["0" * 64],
        )


@pytest.mark.parametrize(
    ("column_name", "value"),
    [
        ("source_word_id", None),
        ("source_word_id", 0),
        ("source_word_id", -1),
        ("source_definition_id", None),
        ("source_definition_id", 0),
        ("source_definition_id", -1),
    ],
)
def test_lexical_definition_inputs_require_positive_source_identifiers_in_sql(
    column_name: str, value: int | None
):
    conn = duckdb.connect(":memory:")
    apply_migrations(conn)
    _seed_dependencies(conn)
    input_values: dict[str, object] = {
        "input_id": "invalid-input",
        "snapshot_id": "snapshot-1",
        "raw_record_id": "raw-1",
        "source_word_id": 10,
        "source_definition_id": 11,
        "input_key": "lexical.book.noun.invalid",
        "source_definition_sha256": "d" * 64,
        "lemma": "book",
        "pos": "noun",
        "frequency_rank": 42,
    }
    input_values[column_name] = value

    with pytest.raises(duckdb.ConstraintException):
        conn.execute(
            """
            INSERT INTO lexical_definition_inputs (
                input_id, snapshot_id, raw_record_id, source_word_id,
                source_definition_id, input_key, source_definition_sha256, lemma,
                pos, frequency_rank
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            list(input_values.values()),
        )


@pytest.mark.parametrize("frequency_rank", [0, -1, 3501])
def test_lexical_definition_inputs_require_rank_in_frozen_scope_in_sql(
    frequency_rank: int,
):
    conn = duckdb.connect(":memory:")
    apply_migrations(conn)
    _seed_dependencies(conn)

    with pytest.raises(duckdb.ConstraintException):
        conn.execute(
            """
            INSERT INTO lexical_definition_inputs (
                input_id, snapshot_id, raw_record_id, source_word_id,
                source_definition_id, input_key, source_definition_sha256, lemma,
                pos, frequency_rank
            ) VALUES ('invalid-rank', 'snapshot-1', 'raw-1', 10, 11,
                      'lexical.book.noun.invalid-rank', ?, 'book', 'noun', ?)
            """,
            ["d" * 64, frequency_rank],
        )


@pytest.mark.parametrize("source_row_id", [None, 0, -1])
def test_lexical_evidence_items_require_positive_source_row_ids_in_sql(
    source_row_id: int | None,
):
    conn = duckdb.connect(":memory:")
    apply_migrations(conn)
    _seed_dependencies(conn)
    _insert_input(conn)

    with pytest.raises(duckdb.ConstraintException):
        conn.execute(
            """
            INSERT INTO lexical_evidence_items (
                evidence_id, input_id, evidence_role, source_row_id, source_name,
                value_json, value_sha256
            ) VALUES ('invalid-evidence', 'input-1', 'definition', ?, 'source', '{}', ?)
            """,
            [source_row_id, "0" * 64],
        )


@pytest.mark.parametrize(
    ("table", "columns", "values"),
    [
        (
            "lexical_evidence_items",
            "evidence_id, input_id, evidence_role, source_row_id, source_name, value_json, value_sha256",
            "'bad-role', 'input-1', 'audio', 1, 'source', '{}', ?",
        ),
        (
            "lexical_evidence_rankings",
            "validation_run_id, input_id, evidence_id, evidence_role, rank, selected, eligible, reason_json",
            "'run-1', 'input-1', 'evidence-1', 'audio', 1, TRUE, TRUE, '{}'",
        ),
        (
            "lexical_input_dispositions",
            "validation_run_id, input_id, state, candidate_id, failure_codes_json, rationale_json, updated_at",
            "'run-1', 'input-1', 'approved', NULL, '[]', '{}', current_timestamp",
        ),
        (
            "lexical_remediation_attempts",
            "attempt_id, validation_run_id, input_id, attempt_number, selection_json, outcome, failure_codes_json, rationale_json, created_at",
            "'bad-outcome', 'run-1', 'input-1', 1, '{}', 'approved', '[]', '{}', current_timestamp",
        ),
        (
            "lexical_quarantine_cases",
            "case_id, input_id, latest_validation_run_id, status, retry_count, failure_codes_json, alternatives_json, updated_at",
            "'bad-status', 'input-1', 'run-1', 'pending', 0, '[]', '[]', current_timestamp",
        ),
    ],
)
def test_lexical_evidence_tables_reject_invalid_lifecycle_values(
    table: str, columns: str, values: str
):
    conn = duckdb.connect(":memory:")
    apply_migrations(conn)
    _seed_dependencies(conn)
    _insert_input(conn)
    if table == "lexical_evidence_rankings":
        _insert_evidence(conn)

    with pytest.raises(duckdb.ConstraintException):
        conn.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({values})",
            ["0" * 64] if table == "lexical_evidence_items" else None,
        )


def test_lexical_disposition_is_unique_per_input_and_validation_run():
    conn = duckdb.connect(":memory:")
    apply_migrations(conn)
    _seed_dependencies(conn)
    _insert_input(conn)
    conn.execute("""
        INSERT INTO lexical_input_dispositions VALUES
        ('run-1', 'input-1', 'quarantined', NULL, '["missing_translation"]', '{}', current_timestamp)
        """)

    with pytest.raises(duckdb.ConstraintException):
        conn.execute("""
            INSERT INTO lexical_input_dispositions VALUES
            ('run-1', 'input-1', 'rejected', NULL, '["duplicate"]', '{}', current_timestamp)
            """)


def test_invalid_evidence_role_rolls_back_the_transaction(tmp_path: Path):
    store = LearningGraphStore(tmp_path / "graph.duckdb")
    store.initialize()
    conn = store.connection()
    _seed_dependencies(conn)

    with pytest.raises(duckdb.ConstraintException), store.transaction() as transaction:
        _insert_input(transaction)
        transaction.execute(
            """
            INSERT INTO lexical_evidence_items VALUES
            ('bad-role', 'input-1', 'audio', 1, 'source', '{}', ?, current_timestamp)
            """,
            ["0" * 64],
        )

    assert conn.execute(
        "SELECT count(*) FROM lexical_definition_inputs"
    ).fetchone() == (0,)
