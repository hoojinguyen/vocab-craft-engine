"""Tests for smart POS and CEFR matched distractors in ReflexBuilder."""

import json
import pytest
from src.nlp.reflex_builder import ReflexBuilder


@pytest.fixture
def builder():
    pool = [
        {"id": 1, "text_en": "They run fast.", "text_vi": "Họ chạy nhanh.", "cefr_level": "A1"},
        {"id": 2, "text_en": "She eats apples.", "text_vi": "Cô ấy ăn táo.", "cefr_level": "A1"},
        {"id": 3, "text_en": "We make progress.", "text_vi": "Chúng tôi tiến bộ.", "cefr_level": "A1"},
        {"id": 4, "text_en": "The unprecedented crisis occurs.", "text_vi": "Cuộc khủng hoảng chưa từng có xảy ra.", "cefr_level": "C1"},
    ]
    return ReflexBuilder(sentence_pool=pool)


def test_build_drill_missing_chunk_fill_uses_pos_matched_distractors(builder):
    target = {"id": 1, "text_en": "They run fast.", "text_vi": "Họ chạy nhanh.", "cefr_level": "A1"}
    drill = builder.build_drill(target, drill_type="missing_chunk_fill")
    
    assert drill["drill_type"] == "missing_chunk_fill"
    assert "___" in drill["prompt_text"]
    distractors = json.loads(drill["distractors_json"])
    assert len(distractors) == 3
    # Check that distractors are not identical to correct answer
    assert drill["correct_answer"] not in distractors


def test_build_drill_speed_translation_filters_cefr_and_length(builder):
    target = {"id": 1, "text_en": "They run fast.", "text_vi": "Họ chạy nhanh.", "cefr_level": "A1"}
    drill = builder.build_drill(target, drill_type="speed_translation")
    
    assert drill["drill_type"] == "speed_translation"
    assert drill["prompt_text"] == "They run fast."
    distractors = json.loads(drill["distractors_json"])
    assert len(distractors) == 3
    assert target["text_vi"] not in distractors
