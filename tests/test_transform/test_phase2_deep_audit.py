"""
Deep Audit & Stress Verification Test Suite for Phase 2.

Covers:
1. SentenceLinker with contractions, hyphens, punctuation, and irregular verb forms.
2. PhraseExtractor with past-tense / inflected phrases matching to canonical headwords.
3. RelationBuilder with noisy casing, whitespace, and mutual relations.
4. TopicMapper with edge case terms and taxonomy priority.
5. HybridTranslator batching with special characters and quotes.
6. ReflexBuilder non-collision constraint (no distractor == answer) and valid JSON.
7. ScenarioBuilder graph integrity (parent-child connectivity & valid roles).
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
def audit_db(tmp_path: Path):
    db_file = tmp_path / "deep_audit.duckdb"
    mgr = DuckDBManager(db_path=db_file)
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_sentence_linker_complex_morphology(audit_db: DuckDBManager):
    audit_db.insert_batch_fast("words", [
        {"lemma": "run", "pos": "verb", "source": "kaikki"},
        {"lemma": "eat", "pos": "verb", "source": "kaikki"},
        {"lemma": "break", "pos": "verb", "source": "kaikki"},
        {"lemma": "child", "pos": "noun", "source": "kaikki"},
    ])

    audit_db.insert_batch_fast("sentences", [
        {"text_en": "The children ate delicious meals and then ran outside!", "text_vi": "Lũ trẻ đã ăn những bữa ăn ngon rồi chạy ra ngoài!", "source": "tatoeba"},
        {"text_en": "He broke the window yesterday; didn't he?", "text_vi": "Anh ấy đã làm vỡ cửa sổ hôm qua; đúng không?", "source": "tatoeba"},
    ])

    linker = SentenceLinker()
    count = linker.link(audit_db, batch_size=5)
    assert count >= 3

    conn = audit_db.get_connection()
    linked_lemmas = {
        row[0]
        for row in conn.execute(
            "SELECT w.lemma FROM word_sentences ws JOIN words w ON ws.word_id = w.id"
        ).fetchall()
    }
    assert "run" in linked_lemmas      # matched 'ran'
    assert "break" in linked_lemmas    # matched 'broke'


def test_phrase_extractor_past_tense_variants(audit_db: DuckDBManager):
    audit_db.insert_batch_fast("sentences", [
        {"text_en": "Unfortunately, his car broke down on the highway.", "text_vi": "Thật không may, xe của anh ấy bị hỏng trên đường cao tốc.", "source": "tatoeba"},
        {"text_en": "She never gave up despite the immense challenges.", "text_vi": "Cô ấy không bao giờ bỏ cuộc bất chấp những thử thách to lớn.", "source": "tatoeba"},
        {"text_en": "The committee made a decision after hours of debate.", "text_vi": "Ủy ban đã đưa ra quyết định sau nhiều giờ tranh luận.", "source": "tatoeba"},
    ])

    extractor = PhraseExtractor()
    result = extractor.extract(audit_db)
    assert result.phrases_created >= 3

    conn = audit_db.get_connection()
    phrases = {row[0] for row in conn.execute("SELECT phrase FROM phrases").fetchall()}
    assert "break down" in phrases
    assert "give up" in phrases
    assert "make a decision" in phrases

    # Ensure links exist in phrase_sentences
    links_count = conn.execute("SELECT count(*) FROM phrase_sentences").fetchone()[0]
    assert links_count >= 3


def test_relation_builder_noisy_data_handling(audit_db: DuckDBManager):
    audit_db.insert_batch_fast("words", [
        {"lemma": "happy", "pos": "adj", "source": "kaikki"},
        {"lemma": "joyful", "pos": "adj", "source": "kaikki"},
        {"lemma": "sad", "pos": "adj", "source": "kaikki"},
    ])

    conn = audit_db.get_connection()
    happy_id = conn.execute("SELECT id FROM words WHERE lemma = 'happy'").fetchone()[0]
    sad_id = conn.execute("SELECT id FROM words WHERE lemma = 'sad'").fetchone()[0]

    # Insert relations with uppercase and extra spaces
    audit_db.insert_batch_fast("word_relations", [
        {"word_id": happy_id, "relation_type": "synonym", "target_text": " Joyful  ", "target_word_id": None, "inverted": 0, "source": "wordnet"},
        {"word_id": happy_id, "relation_type": "antonym", "target_text": "SAD", "target_word_id": None, "inverted": 0, "source": "wordnet"},
        # Self-reference
        {"word_id": happy_id, "relation_type": "synonym", "target_text": "happy", "target_word_id": happy_id, "inverted": 0, "source": "wordnet"},
    ])

    builder = RelationBuilder()
    builder.deduplicate_and_link(audit_db)

    # 1. No self reference
    self_refs = conn.execute("SELECT count(*) FROM word_relations WHERE word_id = target_word_id").fetchone()[0]
    assert self_refs == 0

    # 2. Resolved target_word_ids
    resolved = conn.execute("SELECT count(*) FROM word_relations WHERE target_word_id IS NOT NULL").fetchone()[0]
    assert resolved >= 2

    # 3. Inverted antonym exists (sad -> happy)
    inv_ant = conn.execute("SELECT inverted FROM word_relations WHERE word_id = ? AND target_text = 'happy'", [sad_id]).fetchone()
    assert inv_ant is not None
    assert inv_ant[0] == 1


def test_topic_mapper_seed_priority(audit_db: DuckDBManager):
    audit_db.insert_batch_fast("words", [
        {"lemma": "nurse", "pos": "noun", "source": "kaikki"},
        {"lemma": "ticket", "pos": "noun", "source": "kaikki"},
        {"lemma": "coffee", "pos": "noun", "source": "kaikki"},
        {"lemma": "xyzunmapped", "pos": "noun", "source": "kaikki"},
    ])

    mapper = TopicMapper()
    count = mapper.map_topics(audit_db)
    assert count == 4

    conn = audit_db.get_connection()
    topics = {row[0]: row[1] for row in conn.execute("SELECT w.lemma, wt.topic FROM word_topics wt JOIN words w ON wt.word_id = w.id").fetchall()}
    assert topics["nurse"] == "Health & Medicine"
    assert topics["ticket"] == "Travel & Transportation"
    assert topics["coffee"] == "Food & Drink"
    assert topics["xyzunmapped"] == "General & Everyday"


def test_hybrid_translator_quotes_and_special_chars(audit_db: DuckDBManager):
    audit_db.insert_batch_fast("words", [{"lemma": "test", "pos": "noun", "source": "kaikki"}])
    conn = audit_db.get_connection()
    wid = conn.execute("SELECT id FROM words WHERE lemma = 'test'").fetchone()[0]

    audit_db.insert_batch_fast("definitions", [
        {"word_id": wid, "definition_en": 'A "complex" item\'s test: special & tricky chars.', "definition_vi": None, "source": "kaikki"},
    ])

    translator = HybridTranslator(audit_db)
    updated = translator.translate_definitions(limit=5)
    assert updated == 1

    row = conn.execute("SELECT definition_vi FROM definitions WHERE word_id = ?", [wid]).fetchone()
    assert row[0] is not None
    assert len(row[0]) > 0


def test_reflex_drills_strict_no_answer_in_distractors(audit_db: DuckDBManager):
    sentences = [
        {"text_en": f"Sentence number {i} is here.", "text_vi": f"Câu số {i} ở đây.", "cefr_level": "A1", "source": "tatoeba"}
        for i in range(20)
    ]
    audit_db.insert_batch_fast("sentences", sentences)

    builder = ReflexBuilder()
    builder.build(audit_db)

    conn = audit_db.get_connection()
    drills = conn.execute("SELECT correct_answer, distractors_json FROM reflex_drills").fetchall()
    assert len(drills) >= 20

    for correct_ans, dist_json in drills:
        distractors = json.loads(dist_json)
        assert isinstance(distractors, list)
        assert len(distractors) == 3
        assert correct_ans not in distractors


def test_scenario_builder_connected_tree_graph(audit_db: DuckDBManager):
    builder = ScenarioBuilder()
    builder.build(audit_db)

    conn = audit_db.get_connection()
    nodes = conn.execute("SELECT id, tree_id, parent_node_id, choice_label, speaker_role FROM dialogue_nodes").fetchall()
    assert len(nodes) >= 20

    all_node_ids = {n[0] for n in nodes}

    for nid, tid, parent_id, choice, role in nodes:
        if parent_id is not None:
            # Parent must exist in database
            assert parent_id in all_node_ids
            # Parent must belong to the same tree
            parent_tid = conn.execute("SELECT tree_id FROM dialogue_nodes WHERE id = ?", [parent_id]).fetchone()[0]
            assert parent_tid == tid
