"""
Comprehensive Phase 2 End-to-End NLP Transforms & Enrichment Integration Verification Test.

Validates:
1. SentenceLinker with morphological inflection matching.
2. PhraseExtractor with multi-category MWE and phrase_sentences foreign keys.
3. RelationBuilder deduplication, target_word_id resolution, and symmetric links.
4. TopicMapper taxonomy mapping using theme_map.yaml.
5. HybridTranslator batch translations and bulk DuckDB updates.
6. ReflexBuilder dynamic distractors from sentence pools.
7. ScenarioBuilder branching dialogue trees and parent node links.
8. Zero orphan foreign keys across all Phase 2 staging tables.
"""

import json
import pytest
from pathlib import Path

from src.db.duckdb_manager import DuckDBManager
from src.enrichment.reflex_builder import ReflexBuilder
from src.enrichment.scenario_builder import ScenarioBuilder
from src.enrichment.translation import HybridTranslator
from src.transform.phrase_extractor import PhraseExtractor
from src.transform.relation_builder import RelationBuilder
from src.transform.sentence_linker import SentenceLinker
from src.transform.topic_mapper import TopicMapper


@pytest.fixture
def phase2_db(tmp_path: Path):
    db_file = tmp_path / "phase2_verify.duckdb"
    mgr = DuckDBManager(db_path=db_file)
    mgr.init_schema()

    # Pre-populate sample words
    mgr.insert_batch_fast("words", [
        {"lemma": "doctor", "pos": "noun", "cefr_level": "A2", "source": "kaikki"},
        {"lemma": "patient", "pos": "noun", "cefr_level": "A2", "source": "kaikki"},
        {"lemma": "hospital", "pos": "noun", "cefr_level": "A2", "source": "kaikki"},
        {"lemma": "run", "pos": "verb", "cefr_level": "A1", "source": "kaikki"},
        {"lemma": "start", "pos": "verb", "cefr_level": "A1", "source": "kaikki"},
        {"lemma": "begin", "pos": "verb", "cefr_level": "A1", "source": "kaikki"},
        {"lemma": "computer", "pos": "noun", "cefr_level": "A1", "source": "kaikki"},
        {"lemma": "coffee", "pos": "noun", "cefr_level": "A1", "source": "kaikki"},
    ])

    # Pre-populate sample sentences
    mgr.insert_batch_fast("sentences", [
        {"text_en": "The doctor visited the patient at the hospital.", "text_vi": "Bác sĩ đã đến thăm bệnh nhân tại bệnh viện.", "cefr_level": "A2", "source": "tatoeba"},
        {"text_en": "They are running very fast in the park.", "text_vi": "Họ đang chạy rất nhanh trong công viên.", "cefr_level": "A1", "source": "tatoeba"},
        {"text_en": "You should never give up on your ambitions.", "text_vi": "Bạn không bao giờ nên từ bỏ hoài bão của mình.", "cefr_level": "B1", "source": "tatoeba"},
        {"text_en": "Good luck on your exam, break a leg!", "text_vi": "Chúc may mắn trong kỳ thi, thi tốt nhé!", "cefr_level": "B2", "source": "tatoeba"},
        {"text_en": "Better late than never is true.", "text_vi": "Muộn còn hơn không là điều đúng đắn.", "cefr_level": "A2", "source": "tatoeba"},
    ])

    # Pre-populate sample definitions
    conn = mgr.get_connection()
    doctor_id = conn.execute("SELECT id FROM words WHERE lemma = 'doctor'").fetchone()[0]
    run_id = conn.execute("SELECT id FROM words WHERE lemma = 'run'").fetchone()[0]
    start_id = conn.execute("SELECT id FROM words WHERE lemma = 'start'").fetchone()[0]

    mgr.insert_batch_fast("definitions", [
        {"word_id": doctor_id, "definition_en": "a person licensed to practice medicine", "definition_vi": None, "source": "kaikki"},
        {"word_id": run_id, "definition_en": "to move rapidly on foot", "definition_vi": None, "source": "kaikki"},
    ])

    # Pre-populate raw relations (start -> begin without target_word_id, and self-referencing link)
    mgr.insert_batch_fast("word_relations", [
        {"word_id": start_id, "relation_type": "synonym", "target_text": "begin", "target_word_id": None, "inverted": 0, "source": "wordnet"},
        {"word_id": start_id, "relation_type": "synonym", "target_text": "start", "target_word_id": start_id, "inverted": 0, "source": "wordnet"},
    ])

    yield mgr
    mgr.close()


def test_phase2_full_pipeline_verification(phase2_db: DuckDBManager):
    conn = phase2_db.get_connection()

    # 1. Test Sentence Linker
    linker = SentenceLinker()
    links_count = linker.link(phase2_db, batch_size=2)
    assert links_count > 0
    # Verify 'run' was linked to sentence 2 (which has 'running')
    run_links = conn.execute("""
        SELECT s.text_en FROM word_sentences ws
        JOIN words w ON ws.word_id = w.id
        JOIN sentences s ON ws.sentence_id = s.id
        WHERE w.lemma = 'run'
    """).fetchall()
    assert len(run_links) >= 1
    assert "running" in run_links[0][0]

    # 2. Test Phrase Extractor
    extractor = PhraseExtractor()
    phrases_count = extractor.extract(phase2_db)
    assert phrases_count >= 3
    assert phase2_db.count_rows("phrases") >= 3
    assert phase2_db.count_rows("phrase_sentences") >= 3

    # 3. Test Relation Builder
    rel_builder = RelationBuilder()
    rel_count = rel_builder.deduplicate_and_link(phase2_db)
    assert rel_count >= 2
    # Self-ref must be gone
    self_refs = conn.execute("SELECT count(*) FROM word_relations WHERE word_id = target_word_id").fetchone()[0]
    assert self_refs == 0
    # Inverted link must exist
    inv_links = conn.execute("SELECT count(*) FROM word_relations WHERE inverted = 1").fetchone()[0]
    assert inv_links >= 1

    # 4. Test Topic Mapper
    mapper = TopicMapper()
    topics_count = mapper.map_topics(phase2_db)
    assert topics_count >= 8
    doc_topic = conn.execute("SELECT topic FROM word_topics wt JOIN words w ON wt.word_id = w.id WHERE w.lemma = 'doctor'").fetchone()[0]
    assert doc_topic == "Health & Medicine"

    # 5. Test Hybrid Batch Translator
    translator = HybridTranslator(phase2_db)
    def_trans = translator.translate_definitions(limit=10)
    phrase_trans = translator.translate_phrases(limit=10)
    assert def_trans == 2
    assert phrase_trans >= 3
    null_def_vis = conn.execute("SELECT count(*) FROM definitions WHERE definition_vi IS NULL").fetchone()[0]
    assert null_def_vis == 0

    # 6. Test Reflex Drills Builder
    reflex_builder = ReflexBuilder()
    drills_count = reflex_builder.build(phase2_db)
    assert drills_count >= 5
    drills = conn.execute("SELECT prompt_text, correct_answer, distractors_json FROM reflex_drills").fetchall()
    for prompt, ans, dist_json in drills:
        assert prompt
        assert ans
        distractors = json.loads(dist_json)
        assert ans not in distractors

    # 7. Test Scenario Builder
    scenario_builder = ScenarioBuilder()
    scenarios_count = scenario_builder.build(phase2_db)
    assert scenarios_count >= 4
    assert phase2_db.count_rows("dialogue_trees") >= 4
    assert phase2_db.count_rows("dialogue_nodes") >= 15

    # 8. Foreign Key Integrity Audit across all Phase 2 Tables
    # Check word_sentences
    orphan_ws_word = conn.execute("SELECT count(*) FROM word_sentences ws LEFT JOIN words w ON ws.word_id = w.id WHERE w.id IS NULL").fetchone()[0]
    assert orphan_ws_word == 0
    orphan_ws_sent = conn.execute("SELECT count(*) FROM word_sentences ws LEFT JOIN sentences s ON ws.sentence_id = s.id WHERE s.id IS NULL").fetchone()[0]
    assert orphan_ws_sent == 0

    # Check phrase_sentences
    orphan_ps_phrase = conn.execute("SELECT count(*) FROM phrase_sentences ps LEFT JOIN phrases p ON ps.phrase_id = p.id WHERE p.id IS NULL").fetchone()[0]
    assert orphan_ps_phrase == 0
    orphan_ps_sent = conn.execute("SELECT count(*) FROM phrase_sentences ps LEFT JOIN sentences s ON ps.sentence_id = s.id WHERE s.id IS NULL").fetchone()[0]
    assert orphan_ps_sent == 0

    # Check word_topics
    orphan_wt = conn.execute("SELECT count(*) FROM word_topics wt LEFT JOIN words w ON wt.word_id = w.id WHERE w.id IS NULL").fetchone()[0]
    assert orphan_wt == 0

    # Check reflex_drills
    orphan_drills = conn.execute("SELECT count(*) FROM reflex_drills rd LEFT JOIN sentences s ON rd.sentence_id = s.id WHERE s.id IS NULL").fetchone()[0]
    assert orphan_drills == 0

    # Check dialogue_nodes
    orphan_nodes = conn.execute("SELECT count(*) FROM dialogue_nodes dn LEFT JOIN dialogue_trees dt ON dn.tree_id = dt.id WHERE dt.id IS NULL").fetchone()[0]
    assert orphan_nodes == 0
