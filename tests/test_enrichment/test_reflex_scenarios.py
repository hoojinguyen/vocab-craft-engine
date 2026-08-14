import json
import random
from pathlib import Path

import pytest

from src.db.duckdb_manager import DuckDBManager
from src.enrichment.reflex_builder import ReflexBuilder, _select_indexed_distractors
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


def test_reflex_builder_is_reproducible_when_fixture_insert_order_changes(
    tmp_path: Path,
):
    class UnorderedResult:
        def __init__(self, result):
            self._result = result

        def fetchall(self):
            return self._result.fetchall()[::-1]

    class UnorderedManager(DuckDBManager):
        def get_connection(self):
            connection = super().get_connection()
            if not getattr(self, "shuffle_queries", False):
                return connection

            class ConnectionProxy:
                def execute(self, sql, *args):
                    result = connection.execute(sql, *args)
                    if (
                        "FROM sentences" in sql or "FROM words" in sql
                    ) and "ORDER BY" not in sql.upper():
                        return UnorderedResult(result)
                    return result

                def __getattr__(self, name):
                    return getattr(connection, name)

            return ConnectionProxy()

    sentences = [
        ("I drink hot coffee every morning.", "Tôi uống cà phê nóng mỗi sáng."),
        ("She reads books in the library.", "Cô ấy đọc sách trong thư viện."),
        (
            "They travel to Japan every summer.",
            "Họ đi du lịch Nhật Bản mỗi mùa hè.",
        ),
        ("The weather is very nice today.", "Thời tiết hôm nay rất đẹp."),
        ("We listen to music after dinner.", "Chúng tôi nghe nhạc sau bữa tối."),
        ("My family lives in the country.", "Gia đình tôi sống ở nông thôn."),
    ]
    words = [
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

    managers = []
    outputs = []
    for name, insertion_order in [("first", 1), ("second", -1)]:
        manager = UnorderedManager(db_path=tmp_path / f"{name}.duckdb")
        manager.init_schema()
        managers.append(manager)
        manager.insert_batch_fast(
            "words",
            [
                {
                    "id": index + 1,
                    "lemma": word,
                    "pos": "noun",
                    "source": "test",
                }
                for index, word in (list(enumerate(words))[::insertion_order])
            ],
        )
        manager.insert_batch_fast(
            "sentences",
            [
                {
                    "id": index + 1,
                    "text_en": text_en,
                    "text_vi": text_vi,
                    "cefr_level": "A2",
                    "source": "test",
                }
                for index, (text_en, text_vi) in (
                    list(enumerate(sentences))[::insertion_order]
                )
            ],
        )
        manager.shuffle_queries = True
        ReflexBuilder(seed=7).build(manager)
        outputs.append(manager.get_connection().execute("""
                SELECT drill_type, prompt_text, correct_answer, distractors_json
                FROM reflex_drills
                ORDER BY drill_type, prompt_text, correct_answer, distractors_json
                """).fetchall())

    for manager in managers:
        manager.close()
    assert outputs[0] == outputs[1]


def test_reflex_builder_deduplicates_candidates_across_equivalent_databases(
    tmp_path: Path,
):
    sentences = [
        ("I drink hot coffee every morning.", "Tôi uống cà phê nóng mỗi sáng."),
        ("She reads books in the library.", "Cô ấy đọc sách trong thư viện."),
        ("They travel to Japan every summer.", "Họ đi du lịch Nhật Bản mỗi mùa hè."),
        ("The weather is very nice today.", "Thời tiết hôm nay rất đẹp."),
        ("I drink tea after lunch.", "Tôi uống trà sau bữa trưa."),
        ("He reads stories at home.", "Cô ấy đọc sách trong thư viện."),
        ("We travel abroad in winter.", "Họ đi du lịch Nhật Bản mỗi mùa hè."),
        ("The weather is warm tonight.", "Thời tiết hôm nay rất đẹp."),
    ]
    words = [
        "coffee",
        "coffee",
        "drink",
        "drink",
        "morning",
        "morning",
        "books",
        "books",
        "library",
        "travel",
        "summer",
        "weather",
        "today",
        "music",
        "family",
    ]

    managers = []
    outputs = []
    for name, insertion_order in [("first", 1), ("second", -1)]:
        manager = DuckDBManager(db_path=tmp_path / f"{name}.duckdb")
        manager.init_schema()
        managers.append(manager)
        manager.insert_batch_fast(
            "words",
            [
                {
                    "id": index + 1,
                    "lemma": word,
                    "pos": "noun",
                    "source": "test",
                }
                for index, word in (list(enumerate(words))[::insertion_order])
            ],
        )
        manager.insert_batch_fast(
            "sentences",
            [
                {
                    "id": index + 1,
                    "text_en": text_en,
                    "text_vi": text_vi,
                    "cefr_level": "A2",
                    "source": "test",
                }
                for index, (text_en, text_vi) in (
                    list(enumerate(sentences))[::insertion_order]
                )
            ],
        )
        ReflexBuilder(seed=11).build(manager)
        outputs.append(manager.get_connection().execute("""
                SELECT drill_type, prompt_text, correct_answer, distractors_json
                FROM reflex_drills
                ORDER BY drill_type, prompt_text, correct_answer, distractors_json
                """).fetchall())

    for manager in managers:
        manager.close()

    assert outputs[0] == outputs[1]
    for _, _, correct_answer, distractors_json in outputs[0]:
        distractors = json.loads(distractors_json)
        assert len(distractors) == 3
        assert len({value.casefold() for value in distractors}) == 3
        assert correct_answer.casefold() not in {
            value.casefold() for value in distractors
        }


def test_indexed_speed_selection_reads_only_selected_values():
    class CountingPool:
        def __init__(self, values):
            self.values = values
            self.accesses = 0

        def __len__(self):
            return len(self.values)

        def __getitem__(self, index):
            self.accesses += 1
            return self.values[index]

    pool = CountingPool([f"translation-{index}" for index in range(1000)])
    distractors = _select_indexed_distractors(pool, 500, random.Random(17))

    assert distractors is not None
    assert pool.accesses == 3
    assert len(distractors) == 3
    assert "translation-500" not in distractors


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
