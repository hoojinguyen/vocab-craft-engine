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
    assert graph_catalog.store.fetch_value("SELECT count(*) FROM content_reviews") == 1


def test_edges_require_distinct_approved_revisions(graph_catalog: SourceCatalog):
    repo = ContentRepository(graph_catalog.store)
    candidate_id = _candidate(repo, graph_catalog)
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
