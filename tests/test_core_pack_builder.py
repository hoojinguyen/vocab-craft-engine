"""
Unit + integration tests for the Core 3000 Word Pack builder.
"""

import argparse
import sqlite3
from pathlib import Path

import pytest

from src.export.core_pack_builder import (
    CONTRACTION_MAP,
    normalize_freq_word,
    rank_to_cefr,
    select_core_words,
    select_core_words_with_gates,
)


def test_normalize_freq_word():
    assert normalize_freq_word("  DON'T  ") == "do"
    assert normalize_freq_word("I") == "i"
    assert normalize_freq_word("don") == "do"
    assert normalize_freq_word("apple") == "apple"
    assert normalize_freq_word("") == ""


def test_rank_to_cefr_thresholds():
    assert rank_to_cefr(1) == "A1"
    assert rank_to_cefr(500) == "A1"
    assert rank_to_cefr(501) == "A2"
    assert rank_to_cefr(1500) == "A2"
    assert rank_to_cefr(1501) == "B1"
    assert rank_to_cefr(3500) == "B1"
    assert rank_to_cefr(3501) == "B2"
    assert rank_to_cefr(7000) == "B2"
    assert rank_to_cefr(7001) == "C1"
    assert rank_to_cefr(15000) == "C1"
    assert rank_to_cefr(15001) == "C2"


@pytest.fixture
def small_db(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.executescript(
        """
        CREATE TABLE words (
            id INTEGER PRIMARY KEY, lemma TEXT UNIQUE, pos TEXT,
            ipa_uk TEXT, ipa_us TEXT, frequency_rank INTEGER, cefr_level TEXT
        );
        CREATE TABLE definitions (
            id INTEGER PRIMARY KEY, word_id INTEGER, definition_en TEXT,
            definition_vi TEXT, example TEXT, source TEXT
        );
        CREATE TABLE sentences (
            id INTEGER PRIMARY KEY, text_en TEXT, text_vi TEXT,
            difficulty_score REAL, cefr_level TEXT, audio_path TEXT, source TEXT
        );
        CREATE TABLE word_sentence_map (word_id INTEGER, sentence_id INTEGER);
        CREATE TABLE word_topics (word_id INTEGER, topic TEXT, raw_topic TEXT);
        CREATE TABLE collocations (
            id INTEGER PRIMARY KEY, phrase TEXT, meaning_vi TEXT,
            pos_pattern TEXT, cefr_level TEXT
        );
        CREATE TABLE phrases (
            id INTEGER PRIMARY KEY, phrase TEXT, phrase_type TEXT, pos TEXT,
            cefr_level TEXT, difficulty_score REAL, definition_en TEXT,
            definition_vi TEXT, ipa TEXT, audio_std TEXT, audio_fast TEXT,
            audio_status TEXT
        );
        """
    )
    conn.commit()
    yield conn
    conn.close()


def _insert_words(conn, words):
    for lemma, pos, rank in words:
        conn.execute(
            "INSERT INTO words (lemma, pos, frequency_rank, cefr_level) VALUES (?, ?, ?, 'C2')",
            (lemma, pos, rank),
        )
    conn.commit()


def test_select_core_words_filters_noise_and_ranks(tmp_path, small_db):
    # rank-1 "the" not in words; rank-2 "name" not in words;
    # rank-6 "john" has noise POS "name" -> excluded by the POS filter
    _insert_words(small_db, [
        ("cat", "noun", 3),
        ("dog", "noun", 4),
        ("run", "verb", 5),
        ("john", "name", 6),
        ("happy", "adj", 7),
    ])
    freq = {"the": 1, "name": 2, "cat": 3, "dog": 4, "run": 5, "john": 6, "happy": 7}
    selected = select_core_words(small_db, freq, target=4, window=100)
    lemmas = [w["lemma"] for w in selected]
    assert lemmas == ["cat", "dog", "run", "happy"]  # noise POS "name" excluded
    assert all(w["pos"] != "name" for w in selected)


def test_select_core_words_contraction_join(tmp_path, small_db):
    _insert_words(small_db, [("do", "verb", 1)])
    freq = {"don't": 1, "does": 2, "do": 3}
    selected = select_core_words(small_db, freq, target=1, window=100)
    assert selected[0]["lemma"] == "do"  # "don't" normalizes to "do"


def test_select_core_words_respects_window(tmp_path, small_db):
    _insert_words(small_db, [("cat", "noun", 1), ("dog", "noun", 2)])
    freq = {"cat": 1, "dog": 2}
    selected = select_core_words(small_db, freq, target=5, window=2)
    assert len(selected) == 2  # window exhausted before target


def test_select_core_words_with_gates_returns_metrics(tmp_path, small_db):
    _insert_words(small_db, [
        ("the", "det", 1), ("be", "verb", 2), ("and", "conj", 3),
        ("of", "prep", 4), ("a", "det", 5),
    ])
    small_db.execute("INSERT INTO sentences (text_en, text_vi, cefr_level) VALUES ('the cat and the dog', 'con meo va con cho', 'A1')")
    small_db.commit()
    ngsl = tmp_path / "ngsl.csv"
    ngsl.write_text("the,,,\nbe,,,\nand,,,\nof,,,\na,,,\n", encoding="utf-8")

    selected, metrics = select_core_words_with_gates(
        small_db, freq_dict={"the": 1, "be": 2, "and": 3, "of": 4, "a": 5, "cat": 6},
        ngsl_path=ngsl, target=5,
    )
    assert len(selected) == 5
    assert metrics["ngsl_overlap"] == 1.0
    assert metrics["tatoeba_coverage"] >= 0.5


def test_select_core_words_with_gates_retries_wider_window(tmp_path, small_db):
    # 22 of 26 base words in NGSL -> overlap 22/26 (0.846) < 0.85, gate fails at 3500.
    # At window 4000, "zebra" (rank 4000, in NGSL) joins -> 23/27 (0.852), gate passes.
    base = [f"w{i:02d}" for i in range(1, 27)]
    _insert_words(small_db, [(w, "noun", i) for i, w in enumerate(base, start=1)])
    _insert_words(small_db, [("zebra", "noun", 4000)])
    small_db.execute(
        "INSERT INTO sentences (text_en, text_vi, cefr_level) VALUES (?, ?, 'A1')",
        (" ".join(base + ["zebra"]), "..."),
    )
    small_db.commit()
    ngsl = tmp_path / "ngsl.csv"
    ngsl.write_text("\n".join(base[:22] + ["zebra"]) + "\n", encoding="utf-8")
    freq = {w: i for i, w in enumerate(base, start=1)}
    freq["zebra"] = 4000

    selected, metrics = select_core_words_with_gates(
        small_db, freq_dict=freq, ngsl_path=ngsl, target=3000,
    )
    assert metrics["window"] == 4000  # widened past the failing 3500 attempt
    assert metrics["passed"] is True
    assert metrics["ngsl_overlap"] >= 0.85
    assert len(selected) == 27  # selected grew vs the 26-word 3500 window
    assert metrics["selected"] == 27
    assert selected[-1]["lemma"] == "zebra"


from src.export.core_pack_builder import CorePackBuilder
from src.nlp.vi_validator import VietnameseTextValidator


class StubTranslator:
    """Fake Translator: returns validated Vietnamese for any input."""

    def __init__(self):
        self.calls = []

    def translate_text(self, text):
        self.calls.append(text)
        return f"bản dịch của {text}"

    def save_cache(self):
        pass


def _seed_pack_source(conn):
    conn.executemany(
        "INSERT INTO words (lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level) "
        "VALUES (?, ?, '/x/', '/x/', ?, 'C2')",
        [("cat", "noun", 3), ("dog", "noun", 4), ("run", "verb", 5)],
    )
    cat_id, dog_id, run_id = [r[0] for r in conn.execute("SELECT id FROM words ORDER BY id")]
    conn.executemany(
        "INSERT INTO definitions (word_id, definition_en, definition_vi, example) "
        "VALUES (?, ?, ?, ?)",
        [
            (cat_id, "A small pet animal.", None, "The cat sleeps all day."),
            (dog_id, "A loyal animal.", None, "The dog runs fast."),
            (run_id, "To move quickly.", None, "I run every morning."),
        ],
    )
    conn.executemany(
        "INSERT INTO sentences (text_en, text_vi, difficulty_score, cefr_level) "
        "VALUES (?, ?, ?, ?)",
        [
            ("The cat sleeps all day.", "Con mèo ngủ cả ngày.", 1.5, "A1"),
            ("The dog runs fast.", "Con chó chạy nhanh.", 1.8, "A2"),
            ("I run every morning.", "Tôi chạy mỗi sáng.", 1.6, "A2"),
        ],
    )
    conn.executemany(
        "INSERT INTO word_sentence_map (word_id, sentence_id) VALUES (?, ?)",
        [(cat_id, 1), (dog_id, 2), (run_id, 3)],
    )
    conn.executemany(
        "INSERT INTO word_topics (word_id, topic, raw_topic) VALUES (?, ?, ?)",
        [(cat_id, "Nature & Animals", "zoology"), (dog_id, "Nature & Animals", "zoology")],
    )
    conn.commit()


def test_enrich_word_all_gates_pass(tmp_path, small_db):
    _seed_pack_source(small_db)
    small_db.close()
    builder = CorePackBuilder(source_db_path=tmp_path / "source.db", output_dir=tmp_path / "pack")
    conn = sqlite3.connect(tmp_path / "source.db")

    word_row = conn.execute("SELECT * FROM words WHERE lemma='cat'").fetchone()
    result = builder._enrich_word(conn, word_row, StubTranslator(), builder._topics_by_word(conn))
    assert result["word"]["lemma"] == "cat"
    assert result["definition_vi"] == "bản dịch của A small pet animal."
    assert result["example_en"] == "The cat sleeps all day."
    assert result["example_vi"] == "Con mèo ngủ cả ngày."
    assert result["topic"] == "Nature & Animals"
    assert result["cefr_level"] == "A1"  # rank 3
    conn.close()


def test_enrich_word_quarantine_on_missing_definition(tmp_path, small_db):
    _seed_pack_source(small_db)
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.execute("DELETE FROM definitions WHERE word_id = (SELECT id FROM words WHERE lemma='dog')")
    conn.commit()

    builder = CorePackBuilder(source_db_path=tmp_path / "source.db", output_dir=tmp_path / "pack")
    dog_row = conn.execute("SELECT * FROM words WHERE lemma='dog'").fetchone()
    result = builder._enrich_word(conn, dog_row, StubTranslator())
    assert result["quarantine"] is not None
    assert result["quarantine"] == "definition"
    conn.close()


def test_enrich_word_general_topic_fallback(tmp_path, small_db):
    _seed_pack_source(small_db)
    conn = sqlite3.connect(tmp_path / "source.db")
    builder = CorePackBuilder(source_db_path=tmp_path / "source.db", output_dir=tmp_path / "pack")
    run_row = conn.execute("SELECT * FROM words WHERE lemma='run'").fetchone()
    result = builder._enrich_word(conn, run_row, StubTranslator())
    assert result["topic"] == "General & Everyday"  # no word_topics rows for "run"
    conn.close()


def test_enrich_word_example_recovers_from_later_sense(tmp_path, small_db):
    _seed_pack_source(small_db)
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.execute(
        "INSERT INTO words (lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level) "
        "VALUES ('wolf', 'noun', '/x/', '/x/', 6, 'C2')",
    )
    wolf_id = conn.execute("SELECT id FROM words WHERE lemma='wolf'").fetchone()[0]
    conn.execute(
        "INSERT INTO definitions (word_id, definition_en, definition_vi, example) "
        "VALUES (?, ?, ?, ?)",
        (wolf_id, "First sense.", None, None),
    )
    conn.execute(
        "INSERT INTO definitions (word_id, definition_en, definition_vi, example) "
        "VALUES (?, ?, ?, ?)",
        (wolf_id, "Second sense.", None, "The wolf howls at the moon."),
    )
    conn.commit()

    builder = CorePackBuilder(source_db_path=tmp_path / "source.db", output_dir=tmp_path / "pack")
    wolf_row = conn.execute("SELECT * FROM words WHERE lemma='wolf'").fetchone()
    result = builder._enrich_word(conn, wolf_row, StubTranslator())
    assert result["quarantine"] is None
    assert result["example_en"] == "The wolf howls at the moon."
    assert result["example_vi"] == "bản dịch của The wolf howls at the moon."
    conn.close()


def test_enrich_word_batch_definitions_equivalent(tmp_path, small_db):
    _seed_pack_source(small_db)
    small_db.close()
    builder = CorePackBuilder(source_db_path=tmp_path / "source.db", output_dir=tmp_path / "pack")
    conn = sqlite3.connect(tmp_path / "source.db")

    for lemma in ("cat", "dog", "run"):
        word_row = conn.execute("SELECT * FROM words WHERE lemma=?", (lemma,)).fetchone()
        per_word = builder._enrich_word(conn, word_row, StubTranslator(), builder._topics_by_word(conn))
        batch = builder._enrich_word(
            conn, word_row, StubTranslator(),
            builder._topics_by_word(conn),
            definitions_by_word=builder._definitions_by_word(conn),
        )
        assert batch == per_word
    conn.close()


def test_enrich_word_batch_definitions_missing_quarantines(tmp_path, small_db):
    _seed_pack_source(small_db)
    conn = sqlite3.connect(tmp_path / "source.db")
    conn.execute("DELETE FROM definitions WHERE word_id = (SELECT id FROM words WHERE lemma='dog')")
    conn.commit()

    builder = CorePackBuilder(source_db_path=tmp_path / "source.db", output_dir=tmp_path / "pack")
    dog_row = conn.execute("SELECT * FROM words WHERE lemma='dog'").fetchone()
    result = builder._enrich_word(
        conn, dog_row, StubTranslator(),
        definitions_by_word=builder._definitions_by_word(conn),
    )
    assert result["quarantine"] == "definition"
    conn.close()


import asyncio
import json
from unittest.mock import AsyncMock, patch


def test_generate_dual_speed_word_writes_subdirs(tmp_path):
    from src.media.audio_generator import AudioGenerator

    async def run():
        gen = AudioGenerator(output_dir=tmp_path / "audio", retry_count=1)
        with patch("edge_tts.Communicate.save", new_callable=AsyncMock) as mock_save:
            async def mock_save_side_effect(target_path):
                Path(target_path).write_bytes(b"MOCK_MP3_DATA")

            mock_save.side_effect = mock_save_side_effect
            return await gen.generate_dual_speed_word(42, "hello", voice="en-US-AriaNeural")

    results = asyncio.run(run())
    assert results["standard_path"] is not None
    assert results["fast_path"] is not None
    assert results["standard_path"].name == "w_42_std.mp3"
    assert results["fast_path"].name == "w_42_fast.mp3"
    assert results["standard_path"].parent.name == "std"


def test_checkpoint_resume_skips_done_words(tmp_path, small_db):
    _seed_pack_source(small_db)
    small_db.close()
    builder = CorePackBuilder(source_db_path=tmp_path / "source.db", output_dir=tmp_path / "pack")
    # write the checkpoint file, then reload it into the builder
    builder.checkpoint_path.write_text(
        json.dumps({"done": {"1": True}}), encoding="utf-8"
    )
    builder._cp = builder._load_checkpoint()
    assert builder._is_done(1) is True
    assert builder._is_done(2) is False


def test_checkpoint_roundtrip_no_tmp_lingers(tmp_path, small_db):
    _seed_pack_source(small_db)
    small_db.close()
    builder = CorePackBuilder(source_db_path=tmp_path / "source.db", output_dir=tmp_path / "pack")
    builder._save_checkpoint({"done": {"1": True}})
    assert builder.checkpoint_path.exists()
    assert not builder.checkpoint_path.with_suffix(".json.tmp").exists()
    builder2 = CorePackBuilder(source_db_path=tmp_path / "source.db", output_dir=tmp_path / "pack")
    assert builder2._is_done(1) is True
    assert builder2._is_done(2) is False


def test_build_pack_end_to_end(tmp_path, small_db, monkeypatch):
    _seed_pack_source(small_db)
    import src.export.core_pack_builder as cpb

    class StubPackTranslator:
        def translate_text(self, text):
            return f"bản dịch của {text}"

        def save_cache(self):
            pass

    monkeypatch.setattr("src.nlp.translator.Translator", StubPackTranslator)

    async def fake_audio(self, word_id, lemma):
        return f"audio/std/w_{word_id}_std.mp3", f"audio/fast/w_{word_id}_fast.mp3"

    original = cpb.CorePackBuilder._generate_word_audio
    cpb.CorePackBuilder._generate_word_audio = fake_audio
    try:
        builder = CorePackBuilder(source_db_path=tmp_path / "source.db", output_dir=tmp_path / "pack")
        ngsl = tmp_path / "ngsl.csv"
        ngsl.write_text("cat,,,\ndog,,,\nrun,,,\n", encoding="utf-8")
        freq = {"cat": 1, "dog": 2, "run": 3}
        report = builder.build(freq_dict=freq, ngsl_path=ngsl, vi_budget=10)
    finally:
        cpb.CorePackBuilder._generate_word_audio = original

    assert report["selected"] == 3
    assert report["pass_rate"] == 1.0
    assert report["quarantined"] == 0
    assert report["themes_covered"] >= 1

    pack_conn = sqlite3.connect(builder.db_path)
    assert pack_conn.execute("SELECT count(*) FROM words").fetchone()[0] == 3
    assert pack_conn.execute("SELECT count(*) FROM quarantine").fetchone()[0] == 0
    topics = set(r[0] for r in pack_conn.execute("SELECT topic FROM word_topics"))
    assert topics == {"Nature & Animals", "General & Everyday"}
    audio = pack_conn.execute("SELECT audio_std FROM words WHERE lemma='cat'").fetchone()[0]
    assert audio == "audio/std/w_1_std.mp3"
    pack_conn.close()

    report_file = tmp_path / "pack" / "quality_report.md"
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "pass rate" in content.lower()
    assert "ngsl" in content.lower()


def test_build_pack_from_full_pipeline_db(tmp_path, small_db, monkeypatch):
    """
    Smoke test on a representative source DB: exercises selection with the
    real NGSL file when present and asserts the pack gate invariants.
    """
    from src.export.core_pack_builder import build_report_invariants

    _seed_pack_source(small_db)
    # add a collocation + idiom linked to core words
    cat_id = small_db.execute("SELECT id FROM words WHERE lemma='cat'").fetchone()[0]
    small_db.execute(
        "INSERT INTO collocations (phrase, meaning_vi, pos_pattern, cefr_level) "
        "VALUES ('cat food', 'thức ăn cho mèo', 'noun chunk', 'A1')"
    )
    small_db.execute(
        "INSERT INTO phrases (phrase, phrase_type, cefr_level, definition_en, definition_vi, audio_status) "
        "VALUES ('cat nap', 'idiom', 'A2', 'A short sleep.', 'giấc ngủ ngắn.', 'ok')"
    )
    small_db.commit()
    small_db.close()

    ngsl = tmp_path / "ngsl.csv"
    ngsl.write_text("cat,,,\ndog,,,\nrun,,,\n", encoding="utf-8")

    import src.export.core_pack_builder as cpb

    class StubPackTranslator:
        def translate_text(self, text):
            return f"bản dịch của {text}"

        def save_cache(self):
            pass

    monkeypatch.setattr("src.nlp.translator.Translator", StubPackTranslator)

    async def fake_audio(self, word_id, lemma):
        return f"audio/std/w_{word_id}_std.mp3", f"audio/fast/w_{word_id}_fast.mp3"

    original = cpb.CorePackBuilder._generate_word_audio
    cpb.CorePackBuilder._generate_word_audio = fake_audio
    try:
        builder = CorePackBuilder(source_db_path=tmp_path / "source.db", output_dir=tmp_path / "pack")
        report = builder.build(freq_dict={"cat": 1, "dog": 2, "run": 3},
                               ngsl_path=ngsl, vi_budget=10)
    finally:
        cpb.CorePackBuilder._generate_word_audio = original

    violations = build_report_invariants(builder.db_path, report)
    assert violations == []
    assert report["collocations"] >= 1
    assert report["phrases"] >= 1


def test_example_prefers_cleaner_source(small_db, tmp_path, monkeypatch):
    from src.export.core_pack_builder import CorePackBuilder

    _seed_pack_source(small_db)
    cat_id = small_db.execute("SELECT id FROM words WHERE lemma='cat'").fetchone()[0]

    # both sentences are CEFR-fit for 'cat'; subtitle one has LOWER difficulty,
    # so without source ranking it would win — TED-EnVi must be preferred.
    small_db.execute(
        "INSERT INTO sentences (text_en, text_vi, cefr_level, difficulty_score, source) VALUES "
        "('A cat sits on the mat.', 'Một con mèo ngồi trên thảm.', 'A1', 1.0, 'OpenSubtitles'), "
        "('The cat is sleeping.', 'Con mèo đang ngủ.', 'A1', 1.2, 'TED-EnVi')"
    )
    sent_ids = [r[0] for r in small_db.execute(
        "SELECT id FROM sentences ORDER BY id").fetchall()]
    sub_id, ted_id = sent_ids[-2], sent_ids[-1]
    small_db.execute(
        "INSERT INTO word_sentence_map (word_id, sentence_id) VALUES "
        f"({cat_id}, {sub_id}), ({cat_id}, {ted_id})"
    )
    small_db.commit()

    class StubT:
        def translate_text(self, text): return f"vi: {text}"
        def save_cache(self): pass

    monkeypatch.setattr("src.nlp.translator.Translator", StubT)

    # word_row mirrors the selection tuple: (id, lemma, pos, ipa_uk, ipa_us, freq_rank, cefr)
    word_row = (cat_id, "cat", "noun", "kæt", "kæt", 100, "A2")
    builder = CorePackBuilder(source_db_path=tmp_path, output_dir=tmp_path / "p")
    word = builder._enrich_word(
        small_db, word_row, translator=StubT(),
        topics_by_word={cat_id: ["General & Everyday"]},
        definitions_by_word={cat_id: ("A pet.", "Mèo.", None)},
    )

    assert word["word"]["lemma"] == "cat"
    assert word["example_en"] == "The cat is sleeping."  # TED-EnVi wins over OpenSubtitles