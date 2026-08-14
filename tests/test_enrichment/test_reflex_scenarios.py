import json
from pathlib import Path

import pytest

from src.db.duckdb_manager import DuckDBManager
from src.enrichment.reflex_builder import ReflexBuilder
from src.enrichment.scenario_builder import ScenarioBuilder
from src.pipeline.steps.enrich_reflex import EnrichReflexStep
from src.pipeline.steps.enrich_scenarios import EnrichScenariosStep


@pytest.fixture
def db_mgr(tmp_path: Path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_reflex_drills_generation(db_mgr: DuckDBManager):
    db_mgr.insert_batch_fast(
        "words",
        [
            {"lemma": "coffee", "pos": "noun", "source": "kaikki"},
            {"lemma": "drink", "pos": "verb", "source": "kaikki"},
        ],
    )

    db_mgr.insert_batch_fast(
        "sentences",
        [
            {
                "text_en": "I drink hot coffee every morning.",
                "text_vi": "Tôi uống cà phê nóng mỗi sáng.",
                "cefr_level": "A2",
                "source": "tatoeba",
            },
            {
                "text_en": "She reads books in the library.",
                "text_vi": "Cô ấy đọc sách trong thư viện.",
                "cefr_level": "A2",
                "source": "tatoeba",
            },
            {
                "text_en": "They travel to Japan every summer.",
                "text_vi": "Họ đi du lịch Nhật Bản mỗi mùa hè.",
                "cefr_level": "B1",
                "source": "tatoeba",
            },
            {
                "text_en": "The weather is very nice today.",
                "text_vi": "Thời tiết hôm nay rất đẹp.",
                "cefr_level": "A1",
                "source": "tatoeba",
            },
        ],
    )

    builder = ReflexBuilder()
    count = builder.build(db_mgr)
    assert count >= 4

    conn = db_mgr.get_connection()
    drills = conn.execute(
        "SELECT sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms FROM reflex_drills"
    ).fetchall()
    assert len(drills) >= 4

    drill_types = {d[1] for d in drills}
    assert "speed_translation" in drill_types or "cloze" in drill_types

    for sid, dtype, prompt, ans, dist_json, target_ms in drills:
        assert prompt
        assert ans
        assert target_ms == 2500
        distractors = json.loads(dist_json)
        assert isinstance(distractors, list)
        assert len(distractors) == 3
        # Distractors must not include the correct answer!
        assert ans not in distractors


def _insert_reflex_cap_fixture(db_mgr: DuckDBManager):
    db_mgr.insert_batch_fast(
        "words",
        [
            {"lemma": lemma, "pos": "noun", "source": "test"}
            for lemma in [
                "coffee",
                "drink",
                "morning",
                "books",
                "library",
                "travel",
                "summer",
                "weather",
                "today",
                "music",
                "family",
                "country",
            ]
        ],
    )
    db_mgr.insert_batch_fast(
        "sentences",
        [
            {
                "text_en": text_en,
                "text_vi": text_vi,
                "cefr_level": "A2",
                "source": "test",
            }
            for text_en, text_vi in [
                ("I drink hot coffee every morning.", "Tôi uống cà phê nóng mỗi sáng."),
                ("She reads books in the library.", "Cô ấy đọc sách trong thư viện."),
                (
                    "They travel to Japan every summer.",
                    "Họ đi du lịch Nhật Bản mỗi mùa hè.",
                ),
                ("The weather is very nice today.", "Thời tiết hôm nay rất đẹp."),
                (
                    "We listen to music after dinner.",
                    "Chúng tôi nghe nhạc sau bữa tối.",
                ),
                ("My family lives in the country.", "Gia đình tôi sống ở nông thôn."),
            ]
        ],
    )


def test_reflex_builder_caps_each_drill_type_and_replaces_prior_run(
    db_mgr: DuckDBManager,
):
    _insert_reflex_cap_fixture(db_mgr)
    builder = ReflexBuilder(seed=7, batch_size=2)

    assert builder.build(db_mgr, max_drills_per_type=2) == 4
    counts = (
        db_mgr.get_connection()
        .execute("SELECT drill_type, COUNT(*) FROM reflex_drills GROUP BY drill_type")
        .fetchall()
    )
    assert dict(counts) == {"speed_translation": 2, "cloze": 2}

    assert builder.build(db_mgr, max_drills_per_type=2) == 4
    assert db_mgr.count_rows("reflex_drills") == 4


def test_scenario_trees_generation(db_mgr: DuckDBManager):
    builder = ScenarioBuilder()
    tree_count = builder.build(db_mgr)
    assert tree_count >= 4

    conn = db_mgr.get_connection()
    trees = conn.execute(
        "SELECT id, title, topic, cefr_level FROM dialogue_trees"
    ).fetchall()
    assert len(trees) >= 4

    tree_ids = [t[0] for t in trees]

    nodes = conn.execute(
        "SELECT id, tree_id, parent_node_id, choice_label, speaker_role FROM dialogue_nodes"
    ).fetchall()
    assert len(nodes) >= 15

    # Check that all nodes link to valid trees
    for nid, tid, parent_id, label, role in nodes:
        assert tid in tree_ids
        assert role in ("A", "B")


def test_enrich_reflex_and_scenarios_steps():
    step_reflex = EnrichReflexStep()
    assert step_reflex.name == "enrich_reflex"
    assert "reflex_drills" in step_reflex.produces

    step_scenarios = EnrichScenariosStep()
    assert step_scenarios.name == "enrich_scenarios"
    assert "dialogue_trees" in step_scenarios.produces
    assert "dialogue_nodes" in step_scenarios.produces
