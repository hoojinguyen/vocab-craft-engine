from __future__ import annotations

import hashlib
import json

import pytest

from src.learning.lexical_sampling import LexicalPilotSampler
from src.learning.models import canonical_json


def _seed_snapshot(graph_catalog, count: int = 16) -> str:
    connection = graph_catalog.store.connection()
    connection.execute(
        """
        INSERT INTO source_assets VALUES
        ('kaikki', 'Kaikki', 'https://example.test/kaikki', '1', ?,
         'CC-BY-4.0', 'https://creativecommons.org/licenses/by/4.0/', 'Fixture', TRUE,
         'approved', current_timestamp),
        ('wordnet', 'WordNet', 'https://example.test/wordnet', '1', ?,
         'CC-BY-4.0', 'https://creativecommons.org/licenses/by/4.0/', 'Fixture', TRUE,
         'approved', current_timestamp)
        """,
        ["a" * 64, "b" * 64],
    )
    connection.execute(
        """
        INSERT INTO source_snapshots VALUES
        ('lexical-snapshot', 'kaikki', '/tmp/kaikki.db', current_timestamp, ?, current_timestamp),
        ('other-snapshot', 'wordnet', '/tmp/wordnet.db', current_timestamp, ?, current_timestamp)
        """,
        ["c" * 64, "d" * 64],
    )
    for index in range(count):
        rank = (index * 3500 // count) + 1
        raw_id = f"raw-{index}"
        connection.execute(
            "INSERT INTO raw_reference_records VALUES (?, 'kaikki', ?, 'sqlite_lexical_bundle', '{}', ?, 'fixture', current_timestamp)",
            [raw_id, f"external-{index}", hashlib.sha256(raw_id.encode()).hexdigest()],
        )
        connection.execute(
            """
            INSERT INTO lexical_definition_inputs (
                input_id, snapshot_id, raw_record_id, source_word_id,
                source_definition_id, input_key, source_definition_sha256, lemma,
                pos, frequency_rank
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                f"input-{index}",
                "lexical-snapshot",
                raw_id,
                1000 + index,
                2000 + index,
                f"lexical.word{index}.{'noun' if index % 2 == 0 else 'verb'}.{index}",
                "f" * 64,
                f"word{index}",
                "noun" if index % 2 == 0 else "verb",
                rank,
            ],
        )
    return "lexical-snapshot"


def test_stratified_pilot_is_stable_and_has_requested_size(graph_catalog):
    snapshot_id = _seed_snapshot(graph_catalog)
    sampler = LexicalPilotSampler(graph_catalog.store)

    first = sampler.select(snapshot_id, size=8, seed="pilot-v1")
    second = sampler.select(snapshot_id, size=8, seed="pilot-v1")

    assert first.input_ids == second.input_ids
    assert len(first.input_ids) == 8
    assert {row.rank_band for row in first.rows} == {
        "1-500",
        "501-1500",
        "1501-2500",
        "2501-3500",
    }
    assert first.inventory_sha256 == second.inventory_sha256
    assert all(
        key.startswith(
            (
                "1-500|kaikki|",
                "501-1500|kaikki|",
                "1501-2500|kaikki|",
                "2501-3500|kaikki|",
            )
        )
        for key in first.stratum_counts
    )
    assert {key.rsplit("|", 1)[1] for key in first.stratum_counts} == {"noun", "verb"}


def test_stratified_pilot_rejects_invalid_and_oversized_requests(graph_catalog):
    snapshot_id = _seed_snapshot(graph_catalog, count=4)
    sampler = LexicalPilotSampler(graph_catalog.store)

    with pytest.raises(ValueError, match="contains only"):
        sampler.select(snapshot_id, size=1000, seed="pilot-v1")
    with pytest.raises(ValueError, match="positive"):
        sampler.select(snapshot_id, size=0, seed="pilot-v1")


def test_pilot_metadata_contains_deterministic_canonical_inventory(graph_catalog):
    snapshot_id = _seed_snapshot(graph_catalog)
    selection = LexicalPilotSampler(graph_catalog.store).select(
        snapshot_id, size=8, seed="pilot-v1"
    )

    metadata = selection.as_metadata()
    assert metadata["kind"] == "stratified_pilot_v1"
    assert metadata["seed"] == "pilot-v1"
    assert metadata["input_ids"] == list(selection.input_ids)
    assert metadata["stratum_counts"]
    identities = [row.identity for row in selection.rows]
    expected_hash = hashlib.sha256(canonical_json(identities).encode()).hexdigest()
    assert metadata["inventory_sha256"] == expected_hash
    assert json.dumps(metadata, sort_keys=True) == json.dumps(
        selection.as_metadata(), sort_keys=True
    )
