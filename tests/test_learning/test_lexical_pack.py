from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.learning.catalog import RawRecordInput, SourceCatalog
from src.learning.lexical_pack import LexicalPackComposer
from src.learning.models import CandidateState
from src.learning.repository import ContentRepository


def _sense_payload(index: int, *, bad: bool = False) -> dict[str, object]:
    suffix = chr(ord("a") + index // 26) + chr(ord("a") + index % 26)
    lemma = "badword" if bad else f"lex{suffix}"
    return {
        "stable_key": f"sense.{lemma}.noun.{index:012d}",
        "lemma": lemma,
        "pos": "noun",
        "frequency_rank": 100 + index,
        "cefr_level": "A1",
        "cefr_method": "frequency_rank_v1",
        "definition_en": f"definition of {lemma}",
        "definition_vi": f"nghĩa của {lemma}",
        "ipa_uk": "/lɛks/",
        "ipa_us": "/lɛks/",
        "ipa_source": "kaikki",
        "ipa_confidence": 0.8,
        "examples": [
            {
                "text_en": f"Use {lemma} today.",
                "text_vi": f"Hãy dùng {lemma} hôm nay.",
                "source": "fixture",
            }
        ],
        "source_asset_id": "human-authored-a0",
    }


def _seed_lexical_run(graph_catalog: SourceCatalog) -> str:
    with graph_catalog.store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO source_snapshots (
                snapshot_id, asset_id, local_path, retrieved_at, file_sha256
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                "snapshot-pack",
                "human-authored-a0",
                "/tmp/reference.db",
                datetime.now(UTC),
                "a" * 64,
            ],
        )
        connection.execute(
            """
            INSERT INTO validation_runs (
                validation_run_id, snapshot_id, policy_version, selection_json
            ) VALUES (?, ?, ?, ?)
            """,
            [
                "validation-pack",
                "snapshot-pack",
                "lexical-v1",
                '{"content_type":"sense"}',
            ],
        )
    graph_catalog.append_raw_records(
        [
            RawRecordInput(
                asset_id="human-authored-a0",
                external_key=f"pack:{index}",
                record_type="sqlite_lexical_bundle",
                payload={"word": {"lemma": f"lex{index:02d}"}},
                import_run_id="pack-import",
            )
            for index in range(31)
        ]
    )
    repository = ContentRepository(graph_catalog.store)
    raw_ids = (
        graph_catalog.store.connection()
        .execute(
            "SELECT raw_record_id FROM raw_reference_records ORDER BY external_key"
        )
        .fetchall()
    )
    for index, (raw_id,) in enumerate(raw_ids):
        candidate_id = repository.create_candidate(
            str(raw_id), "sense", _sense_payload(index), {"fixture": True}, 1.0
        )
        repository.mark_candidate_validated(candidate_id)
        graph_catalog.store.connection().execute(
            """
            INSERT INTO candidate_gate_results (
                validation_run_id, candidate_id, gate_code, passed, message, details_json
            ) VALUES (?, ?, ?, TRUE, ?, ?)
            """,
            ["validation-pack", candidate_id, "sense.complete", "passed", "{}"],
        )
        if index < 30:
            repository.review_candidate(
                candidate_id, "approved", "editor-1", "Reviewed"
            )
    return "validation-pack"


def test_lexical_pack_contains_only_approved_senses_from_validation_run(
    graph_catalog: SourceCatalog,
):
    validation_run_id = _seed_lexical_run(graph_catalog)

    pack = LexicalPackComposer(ContentRepository(graph_catalog.store)).compose(
        validation_run_id, "lexical-a1", "0.1.0", "A1"
    )

    assert len(pack.senses) == 30
    assert "badword" not in {str(sense["lemma"]) for sense in pack.senses}
    assert pack.quality_report["passed"] is True
    assert [sense["frequency_rank"] for sense in pack.senses] == sorted(
        sense["frequency_rank"] for sense in pack.senses
    )


def test_lexical_pack_rejects_empty_or_under_review_selection(
    graph_catalog: SourceCatalog,
):
    validation_run_id = _seed_lexical_run(graph_catalog)
    repository = ContentRepository(graph_catalog.store)

    with pytest.raises(ValueError, match="selection is empty"):
        LexicalPackComposer(repository).compose(
            validation_run_id, "lexical-a2", "0.1.0", "A2"
        )

    assert (
        graph_catalog.store.fetch_value(
            "SELECT count(*) FROM content_candidates WHERE state = ?",
            [CandidateState.VALIDATED.value],
        )
        == 1
    )
