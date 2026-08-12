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


def test_tier_by_tier_distractor_sampling():
    target = {"id": 1, "lemma": "abandon", "pos": "verb", "cefr_level": "B2", "text_vi": "rời bỏ"}
    words = [
        target,
        {"id": 2, "lemma": "obtain", "pos": "verb", "cefr_level": "B2", "text_vi": "đạt được"},
        {"id": 3, "lemma": "replace", "pos": "verb", "cefr_level": "B2", "text_vi": "thay thế"},
        {"id": 4, "lemma": "neglect", "pos": "verb", "cefr_level": "B2", "text_vi": "bỏ mặc"},
        # Tier 2 words (same POS, different CEFR)
        {"id": 5, "lemma": "run", "pos": "verb", "cefr_level": "A1", "text_vi": "chạy"},
        {"id": 6, "lemma": "walk", "pos": "verb", "cefr_level": "A1", "text_vi": "đi bộ"}
    ]
    builder = QuizBuilder(words=words)
    distractors = builder._get_distractors(target, field="text_vi", count=3)
    
    # Tier 1 has 3 valid candidates (obtain, replace, neglect). Distractors MUST be strictly from Tier 1.
    tier1_glosses = {"đạt được", "thay thế", "bỏ mặc"}
    assert len(distractors) == 3
    assert set(distractors) == tier1_glosses
    assert "chạy" not in distractors
    assert "đi bộ" not in distractors


def test_pos_aware_fallback_distractors():
    noun_word = {"id": 1, "lemma": "cat", "pos": "noun", "cefr_level": "A1", "text_vi": "con mèo"}
    words = [noun_word]
    
    builder = QuizBuilder(words=words)
    quiz = builder.generate_word_mcq(noun_word)
    
    options = json.loads(quiz["options_json"])
    assert len(options) == 4
    assert "con mèo" in options
    # Check that distractors are noun fallbacks, not verb fallbacks like "thay đổi"
    assert "thay đổi" not in options
    assert "đạt được" not in options


def test_duplicate_lemma_prevention():
    target = {"id": 1, "lemma": "abandon", "pos": "verb", "cefr_level": "B2", "text_vi": "rời bỏ"}
    words = [
        target,
        {"id": 2, "lemma": "obtain", "pos": "verb", "cefr_level": "B2", "text_vi": "đạt được"},
        {"id": 3, "lemma": "obtain", "pos": "verb", "cefr_level": "B2", "text_vi": "giành được"}  # same lemma, diff gloss
    ]
    builder = QuizBuilder(words=words)
    distractors = builder._get_distractors(target, field="lemma", count=2)
    # Verify obtain is only included once in distractors
    assert distractors.count("obtain") == 1
    assert len(distractors) == 2


def test_lemma_dict_and_cloze_token_lookup():
    words = [
        {"id": 1, "lemma": "abandon", "pos": "verb", "cefr_level": "B2", "text_vi": "rời bỏ"},
        {"id": 2, "lemma": "obtain", "pos": "verb", "cefr_level": "B2", "text_vi": "đạt được"}
    ]
    builder = QuizBuilder(words=words)
    assert builder.lemma_dict["abandon"]["id"] == 1
    assert builder.lemma_dict["obtain"]["id"] == 2

    sentence = {"id": 10, "text_en": "She decided to abandon her old car.", "cefr_level": "B2"}
    quiz = builder.generate_sentence_cloze(sentence)
    assert quiz["correct_answer"] == "abandon"
    assert "___" in quiz["prompt_text"]

    pattern = {"id": 100, "example_en": "It is necessary to obtain approval.", "cefr_level": "B2"}
    p_quiz = builder.generate_pattern_cloze(pattern)
    assert p_quiz["correct_answer"] == "obtain"
    assert "___" in p_quiz["prompt_text"]


def test_tier3_fast_sampling():
    target = {"id": 1, "lemma": "abandon", "pos": "verb", "cefr_level": "B2", "text_vi": "rời bỏ"}
    # Create words with non-matching POS to force Tier 3 sampling
    words = [target] + [
        {"id": i, "lemma": f"word{i}", "pos": "noun", "cefr_level": "A1", "text_vi": f"nghĩa {i}"}
        for i in range(2, 200)
    ]
    builder = QuizBuilder(words=words)
    distractors = builder._get_distractors(target, field="text_vi", count=3)
    assert len(distractors) == 3
    for d in distractors:
        assert d != "rời bỏ"

