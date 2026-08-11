import json
import pytest
from src.nlp.quiz_builder import QuizBuilder


def test_quiz_builder_generators():
    words = [
        {"id": 1, "lemma": "abandon", "pos": "verb", "cefr_level": "B2", "text_vi": "rời bỏ, từ bỏ"},
        {"id": 2, "lemma": "obtain", "pos": "verb", "cefr_level": "B2", "text_vi": "đạt được"},
        {"id": 3, "lemma": "replace", "pos": "verb", "cefr_level": "B2", "text_vi": "thay thế"},
        {"id": 4, "lemma": "neglect", "pos": "verb", "cefr_level": "B2", "text_vi": "bỏ mặc"},
        {"id": 5, "lemma": "apple", "pos": "noun", "cefr_level": "A1", "text_vi": "quả táo"}
    ]
    sentences = [
        {"id": 10, "text_en": "She decided to abandon her old car.", "text_vi": "Cô ấy quyết định từ bỏ chiếc xe cũ.", "cefr_level": "B2"}
    ]
    patterns = [
        {"id": 100, "pattern_name": "it_is_adj_to_v", "example_en": "It is important to learn English.", "cefr_level": "A2"}
    ]

    builder = QuizBuilder()
    quizzes = builder.build_all_quizzes(words=words, sentences=sentences, patterns=patterns)
    assert len(quizzes) >= 4

    types = {q["question_type"] for q in quizzes}
    assert "word_mcq" in types
    assert "sentence_cloze" in types
    assert "pattern_cloze" in types
    assert "word_ordering" in types

    word_mcq = next(q for q in quizzes if q["question_type"] == "word_mcq")
    options = json.loads(word_mcq["options_json"])
    assert len(options) == 4
    assert word_mcq["correct_answer"] in options
    # Verify distractors are verbs, not nouns
    assert "quả táo" not in options


def test_pos_cefr_indexing():
    words = [
        {"id": 1, "lemma": "abandon", "pos": "verb", "cefr_level": "B2", "text_vi": "rời bỏ"},
        {"id": 2, "lemma": "obtain", "pos": "verb", "cefr_level": "b2", "text_vi": "đạt được"},
        {"id": 3, "lemma": "cat", "pos": "noun", "cefr_level": "A1", "text_vi": "con mèo"}
    ]
    builder = QuizBuilder()
    builder._index_words(words)
    
    verb_b2 = builder.pos_cefr_index.get(("verb", "B2"), [])
    assert len(verb_b2) == 2
    noun_a1 = builder.pos_cefr_index.get(("noun", "A1"), [])
    assert len(noun_a1) == 1


def test_generate_sentence_cloze():
    words = [
        {"id": 1, "lemma": "abandon", "pos": "verb", "cefr_level": "B2", "text_vi": "rời bỏ"},
        {"id": 2, "lemma": "obtain", "pos": "verb", "cefr_level": "B2", "text_vi": "đạt được"},
        {"id": 3, "lemma": "replace", "pos": "verb", "cefr_level": "B2", "text_vi": "thay thế"},
        {"id": 4, "lemma": "neglect", "pos": "verb", "cefr_level": "B2", "text_vi": "bỏ mặc"}
    ]
    sentence = {"id": 10, "text_en": "She decided to abandon her old car.", "text_vi": "Cô ấy quyết định từ bỏ chiếc xe cũ.", "cefr_level": "B2"}
    
    builder = QuizBuilder(words=words)
    quiz = builder.generate_sentence_cloze(sentence)
    
    assert quiz["question_type"] == "sentence_cloze"
    assert quiz["target_type"] == "sentence"
    assert quiz["target_id"] == 10
    assert "___" in quiz["prompt_text"]
    assert quiz["correct_answer"] == "abandon"
    
    options = json.loads(quiz["options_json"])
    assert len(options) == 4
    assert "abandon" in options


def test_generate_pattern_cloze():
    words = [
        {"id": 1, "lemma": "important", "pos": "adj", "cefr_level": "A2", "text_vi": "quan trọng"},
        {"id": 2, "lemma": "difficult", "pos": "adj", "cefr_level": "A2", "text_vi": "khó khăn"},
        {"id": 3, "lemma": "easy", "pos": "adj", "cefr_level": "A2", "text_vi": "dễ dàng"},
        {"id": 4, "lemma": "possible", "pos": "adj", "cefr_level": "A2", "text_vi": "có thể"}
    ]
    pattern = {"id": 100, "pattern_name": "it_is_adj_to_v", "example_en": "It is important to learn English.", "cefr_level": "A2"}
    
    builder = QuizBuilder(words=words)
    quiz = builder.generate_pattern_cloze(pattern)
    
    assert quiz["question_type"] == "pattern_cloze"
    assert quiz["target_type"] == "pattern"
    assert quiz["target_id"] == 100
    assert "___" in quiz["prompt_text"]
    assert quiz["correct_answer"] == "important"
    
    options = json.loads(quiz["options_json"])
    assert len(options) == 4
    assert "important" in options


def test_generate_word_ordering():
    sentence = {"id": 10, "text_en": "She decided to abandon her old car.", "text_vi": "Cô ấy quyết định từ bỏ chiếc xe cũ.", "cefr_level": "B2"}
    
    builder = QuizBuilder()
    quiz = builder.generate_word_ordering(sentence)
    
    assert quiz["question_type"] == "word_ordering"
    assert quiz["target_type"] == "sentence"
    assert quiz["target_id"] == 10
    assert quiz["correct_answer"] == "She decided to abandon her old car."
    
    tokens = json.loads(quiz["options_json"])
    assert len(tokens) == 7
    assert set(tokens) == set(["She", "decided", "to", "abandon", "her", "old", "car."])


def test_fallback_distractors_when_pool_is_small():
    words = [
        {"id": 1, "lemma": "abandon", "pos": "verb", "cefr_level": "B2", "text_vi": "rời bỏ"}
    ]
    builder = QuizBuilder(words=words)
    quiz = builder.generate_word_mcq(words[0])
    
    options = json.loads(quiz["options_json"])
    assert len(options) == 4
    assert quiz["correct_answer"] in options
    # Must have 4 unique options
    assert len(set(options)) == 4
