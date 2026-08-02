"""
Unit tests for NLP and Reflex Engine in src.nlp
"""

import json
import pytest
from src.nlp.cefr_grader import CEFRGrader
from src.nlp.lemmatizer import Lemmatizer
from src.nlp.chunk_extractor import ChunkExtractor
from src.nlp.reflex_builder import ReflexBuilder
from src.nlp.scenario_builder import ScenarioBuilder


def test_cefr_grader_words_and_sentences():
    freq_dict = {"the": 1, "apple": 500, "ubiquitous": 15000}
    grader = CEFRGrader(freq_dict)

    lvl_the, _ = grader.grade_word("the")
    lvl_apple, _ = grader.grade_word("apple")
    lvl_ubiq, _ = grader.grade_word("ubiquitous")

    assert lvl_the == "A1"
    assert lvl_apple == "A1"
    assert lvl_ubiq == "C1"

    sentence_res = grader.grade_sentence("The apple is ubiquitous.")
    assert "difficulty_score" in sentence_res
    assert sentence_res["cefr_level"] in ("B2", "C1", "C2")


def test_lemmatizer_single_and_batch():
    lemmatizer = Lemmatizer()
    tokens = lemmatizer.lemmatize_text("The fast cats are running quickly.")

    lemmas = [t["lemma"] for t in tokens]
    assert "cat" in lemmas or "cats" in lemmas or "run" in lemmas

    sentences = [
        {"id": 1, "text_en": "Dogs are barking loudly."},
        {"id": 2, "text_en": "She enjoys reading books."}
    ]
    batch_results = list(lemmatizer.process_sentence_batch(sentences))
    assert len(batch_results) == 2


def test_chunk_extractor():
    extractor = ChunkExtractor()
    text = "We should take a break and look forward to the vacation."
    collocations = extractor.extract_collocations(text)

    phrases = [c["phrase"] for c in collocations]
    assert any("take" in p for p in phrases) or any("look" in p for p in phrases) or len(collocations) > 0


def test_reflex_builder():
    pool = [
        {"id": 1, "text_en": "Good morning!", "text_vi": "Chào buổi sáng!", "cefr_level": "A1"},
        {"id": 2, "text_en": "How are you?", "text_vi": "Bạn khỏe không?", "cefr_level": "A1"},
        {"id": 3, "text_en": "See you later.", "text_vi": "Hẹn gặp lại sau.", "cefr_level": "A1"},
        {"id": 4, "text_en": "Thank you very much.", "text_vi": "Cảm ơn rất nhiều.", "cefr_level": "A1"}
    ]

    builder = ReflexBuilder(sentence_pool=pool)
    target = pool[0]

    drill = builder.build_drill(target, drill_type="speed_translation")

    assert drill["sentence_id"] == 1
    assert drill["drill_type"] == "speed_translation"
    assert drill["prompt_text"] == "Good morning!"
    assert drill["correct_answer"] == "Chào buổi sáng!"
    assert drill["target_time_ms"] == 2500

    distractors = json.loads(drill["distractors_json"])
    assert isinstance(distractors, list)
    assert len(distractors) == 3
    assert "Chào buổi sáng!" not in distractors


def test_scenario_builder():
    builder = ScenarioBuilder()
    tree = builder.create_scenario_tree(title="At the Cafe", topic="Ordering", cefr_level="A2")

    assert tree["title"] == "At the Cafe"
    assert tree["cefr_level"] == "A2"

    node = builder.add_node(tree_id=1, speaker_role="A", sentence_id=10, parent_node_id=None, choice_label="Order Coffee")
    assert node["speaker_role"] == "A"
    assert node["choice_label"] == "Order Coffee"
