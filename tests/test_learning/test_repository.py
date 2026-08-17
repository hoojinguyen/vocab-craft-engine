import json

import pytest

from src.learning.catalog import SourceCatalog
from src.learning.repository import ContentRepository


def _candidate(repo: ContentRepository, catalog: SourceCatalog) -> str:
    raw_id = catalog.record_raw_snapshot(
        "human-authored-a0",
        "objective:greeting",
        {"v": 1},
    )
    return repo.create_candidate(
        raw_id,
        "objective",
        {
            "stable_key": "objective.a0.greet",
            "code": "A0.GREET",
            "outcome": "Greet a person",
        },
        {"source": "editorial"},
        0.95,
    )


def test_approval_creates_versioned_revision_and_preserves_prior_revision(
    graph_catalog: SourceCatalog,
):
    repo = ContentRepository(graph_catalog.store)
    candidate_id = _candidate(repo, graph_catalog)
    repo.mark_candidate_validated(candidate_id)

    revision_1 = repo.review_candidate(
        candidate_id, "approved", "editor-1", "Reviewed for pilot"
    )
    assert revision_1 is not None
    revision_2 = repo.create_revision(
        revision_1,
        {
            "stable_key": "objective.a0.greet",
            "code": "A0.GREET",
            "outcome": "Greet a person politely",
        },
        "editor-1",
        "Clarified outcome",
    )

    assert repo.get_revision(revision_1)["revision_number"] == 1
    assert repo.get_revision(revision_2)["revision_number"] == 2
    assert (
        json.loads(repo.get_revision(revision_1)["payload_json"])["outcome"]
        == "Greet a person"
    )
    assert repo.get_latest_approved_revision("objective.a0.greet") == revision_2


def test_candidate_requires_existing_approved_raw_source(graph_catalog: SourceCatalog):
    repo = ContentRepository(graph_catalog.store)

    with pytest.raises(ValueError, match="raw record"):
        repo.create_candidate(
            "missing-raw-id", "objective", {"code": "A0.GREET"}, {}, 0.5
        )


def test_candidate_payload_requires_stable_key(graph_catalog: SourceCatalog):
    repo = ContentRepository(graph_catalog.store)
    raw_id = graph_catalog.record_raw_snapshot(
        "human-authored-a0", "objective:missing-key", {"v": 1}
    )

    with pytest.raises(ValueError, match="stable_key"):
        repo.create_candidate(raw_id, "objective", {"code": "A0.GREET"}, {}, 0.5)


def test_create_candidate_returns_existing_id_for_same_normalized_payload(
    graph_catalog: SourceCatalog,
):
    repo = ContentRepository(graph_catalog.store)
    raw_id = graph_catalog.record_raw_snapshot(
        "human-authored-a0", "sense:book", {"v": 1}
    )
    payload = {
        "stable_key": "sense.book.noun.123456789abc",
        "definition_en": "a set of pages",
    }

    first = repo.create_candidate(raw_id, "sense", payload, {"source": "fixture"}, 1.0)
    second = repo.create_candidate(
        raw_id,
        "sense",
        {
            "definition_en": "a set of pages",
            "stable_key": "sense.book.noun.123456789abc",
        },
        {"source": "different evidence"},
        0.1,
    )

    assert second == first
    assert (
        graph_catalog.store.fetch_value("SELECT count(*) FROM content_candidates") == 1
    )


def test_create_candidate_does_not_dedupe_distinct_sense_payloads(
    graph_catalog: SourceCatalog,
):
    repo = ContentRepository(graph_catalog.store)
    raw_id = graph_catalog.record_raw_snapshot(
        "human-authored-a0", "word:book", {"v": 1}
    )

    first = repo.create_candidate(
        raw_id,
        "sense",
        {
            "stable_key": "sense.book.noun.111111111111",
            "definition_en": "a set of pages",
        },
        {},
        1.0,
    )
    second = repo.create_candidate(
        raw_id,
        "sense",
        {"stable_key": "sense.book.verb.222222222222", "definition_en": "to reserve"},
        {},
        1.0,
    )

    assert second != first
    assert (
        graph_catalog.store.fetch_value("SELECT count(*) FROM content_candidates") == 2
    )


def test_candidate_requires_validation_before_approval(graph_catalog: SourceCatalog):
    repo = ContentRepository(graph_catalog.store)
    candidate_id = _candidate(repo, graph_catalog)

    with pytest.raises(ValueError, match="validated"):
        repo.review_candidate(candidate_id, "approved", "editor-1", "Reviewed")

    repo.mark_candidate_validated(candidate_id)

    assert repo.review_candidate(candidate_id, "approved", "editor-1", "Reviewed")


def test_candidate_validation_only_allows_candidate_to_validated(
    graph_catalog: SourceCatalog,
):
    repo = ContentRepository(graph_catalog.store)
    candidate_id = _candidate(repo, graph_catalog)

    repo.mark_candidate_validated(candidate_id)

    with pytest.raises(ValueError, match="candidate"):
        repo.mark_candidate_validated(candidate_id)
    with pytest.raises(ValueError, match="does not exist"):
        repo.mark_candidate_validated("missing-candidate")


def test_review_cannot_repeat_after_terminal_decision(graph_catalog: SourceCatalog):
    repo = ContentRepository(graph_catalog.store)
    candidate_id = _candidate(repo, graph_catalog)

    assert (
        repo.review_candidate(candidate_id, "quarantined", "editor-1", "Incomplete")
        is None
    )

    with pytest.raises(ValueError, match="already been reviewed"):
        repo.review_candidate(candidate_id, "rejected", "editor-1", "Repeated review")


def test_rejected_candidate_has_no_canonical_content(graph_catalog: SourceCatalog):
    repo = ContentRepository(graph_catalog.store)
    candidate_id = _candidate(repo, graph_catalog)

    assert (
        repo.review_candidate(candidate_id, "rejected", "editor-1", "Out of scope")
        is None
    )
    assert (
        graph_catalog.store.fetch_value("SELECT count(*) FROM canonical_content") == 0
    )
    assert (
        graph_catalog.store.fetch_value("SELECT count(*) FROM content_revisions") == 0
    )
    assert graph_catalog.store.fetch_value("SELECT count(*) FROM content_reviews") == 1


@pytest.mark.parametrize("decision", ["rejected", "quarantined"])
def test_validated_candidate_can_receive_non_approval_review(
    graph_catalog: SourceCatalog, decision: str
):
    repo = ContentRepository(graph_catalog.store)
    candidate_id = _candidate(repo, graph_catalog)
    repo.mark_candidate_validated(candidate_id)

    assert (
        repo.review_candidate(candidate_id, decision, "editor-1", "Incomplete") is None
    )
    assert (
        graph_catalog.store.fetch_value(
            "SELECT state FROM content_candidates WHERE candidate_id = ?",
            [candidate_id],
        )
        == decision
    )


def test_edges_require_distinct_approved_revisions(graph_catalog: SourceCatalog):
    repo = ContentRepository(graph_catalog.store)
    candidate_id = _candidate(repo, graph_catalog)
    repo.mark_candidate_validated(candidate_id)
    revision_1 = repo.review_candidate(candidate_id, "approved", "editor-1", "Reviewed")
    assert revision_1 is not None
    revision_2 = repo.create_revision(
        revision_1,
        {
            "stable_key": "objective.a0.greet",
            "code": "A0.GREET",
            "outcome": "Greet politely",
        },
        "editor-1",
        "Updated",
    )

    with pytest.raises(ValueError, match="self-link"):
        repo.add_edge(revision_1, revision_1, "precedes")
    assert repo.add_edge(revision_1, revision_2, "precedes", {"weight": 1})


def test_candidate_query_helpers_decode_payload_and_sort_validation_candidates(
    graph_catalog: SourceCatalog,
):
    repo = ContentRepository(graph_catalog.store)
    first_id = _candidate(repo, graph_catalog)
    second_id = repo.create_candidate(
        graph_catalog.record_raw_snapshot(
            "human-authored-a0", "sense:second", {"v": 2}
        ),
        "sense",
        {"stable_key": "sense.second.noun.123456789abc", "definition_en": "next"},
        {"source": "fixture"},
        0.9,
    )
    with graph_catalog.store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO source_snapshots (snapshot_id, asset_id, local_path, retrieved_at, file_sha256)
            VALUES (?, ?, ?, current_timestamp, ?)
            """,
            ["snapshot-1", "human-authored-a0", "/tmp/source.json", "a" * 64],
        )
        connection.execute(
            """
            INSERT INTO validation_runs (validation_run_id, snapshot_id, policy_version, selection_json)
            VALUES (?, ?, ?, ?)
            """,
            ["validation-1", "snapshot-1", "v1", "{}"],
        )
        connection.execute(
            """
            INSERT INTO candidate_gate_results (
                validation_run_id, candidate_id, gate_code, passed, message, details_json
            ) VALUES (?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?)
            """,
            [
                "validation-1",
                second_id,
                "sense.complete",
                True,
                "complete",
                "{}",
                "validation-1",
                first_id,
                "sense.complete",
                True,
                "complete",
                "{}",
            ],
        )

    assert repo.candidate_payload(first_id) == {
        "stable_key": "objective.a0.greet",
        "code": "A0.GREET",
        "outcome": "Greet a person",
    }
    assert [
        row["candidate_id"]
        for row in repo.candidates_for_validation_run("validation-1")
    ] == sorted([first_id, second_id])
    assert all(
        set(row) == {"candidate_id", "raw_record_id", "content_type", "state"}
        for row in repo.candidates_for_validation_run("validation-1")
    )
