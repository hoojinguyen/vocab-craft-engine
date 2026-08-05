"""Integration test: ingest parallel corpus → link → pack coverage improves."""

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace


def _make_corpus(tmp_path: Path, source: str) -> Path:
    en = tmp_path / f"{source}.en"
    vi = tmp_path / f"{source}.vi"
    en.write_text("The cat sleeps on the sofa.\nI run every morning.\n", encoding="utf-8")
    vi.write_text("Con mèo ngủ trên ghế sofa.\nTôi chạy mỗi sáng.\n", encoding="utf-8")
    return tmp_path


def test_ingest_links_and_reports(tmp_path, monkeypatch):
    """Small-DB end-to-end: corpus files → sentences rows → word links."""
    from src.ingestion.sentence_filter import SentenceFilter
    from src.ingestion.opus_parser import ParallelCorpusParser

    db = sqlite3.connect(tmp_path / "db.sqlite")
    db.executescript(
        """
        CREATE TABLE words (id INTEGER PRIMARY KEY, lemma TEXT UNIQUE, pos TEXT);
        CREATE TABLE sentences (
            id INTEGER PRIMARY KEY, text_en TEXT, text_vi TEXT,
            difficulty_score REAL, cefr_level TEXT, audio_path TEXT, source TEXT
        );
        CREATE TABLE word_sentence_map (word_id INTEGER, sentence_id INTEGER);
        """
    )
    db.execute("INSERT INTO words (lemma, pos) VALUES ('cat', 'noun'), ('run', 'verb')")
    db.commit()

    corpus_dir = _make_corpus(tmp_path, "ted")
    sf = SentenceFilter()
    parser = ParallelCorpusParser(corpus_dir / "ted.en", corpus_dir / "ted.vi", source="TED-EnVi")
    inserted = 0
    for pair in parser.parse_pairs():
        if sf.is_clean_pair(pair["text_en"], pair["text_vi"]):
            db.execute(
                "INSERT INTO sentences (text_en, text_vi, cefr_level, difficulty_score, source) "
                "VALUES (?, ?, 'A1', 1.0, ?)",
                (pair["text_en"], pair["text_vi"], pair["source"]),
            )
            inserted += 1
    db.commit()
    assert inserted == 2

    # link via lemma match on the sentence subject word
    for s_id, t_en in db.execute("SELECT id, text_en FROM sentences"):
        lemma = t_en.split()[1].lower().strip(".")
        row = db.execute("SELECT id FROM words WHERE lemma=?", (lemma,)).fetchone()
        if row:
            db.execute(
                "INSERT OR IGNORE INTO word_sentence_map (word_id, sentence_id) VALUES (?, ?)",
                (row[0], s_id),
            )
    db.commit()
    links = db.execute("SELECT count(*) FROM word_sentence_map").fetchone()[0]
    assert links >= 1
    db.close()


def _make_seeded_db(tmp_path: Path):
    """Real DatabaseManager DB with 2 words and 2 sentences (ids 1-2)."""
    from src.db.staging_db import DatabaseManager

    db_manager = DatabaseManager(db_path=tmp_path / "pipeline.db")
    db_manager.init_schema()
    db_manager.insert_words_batch([
        {"lemma": "cat", "pos": "noun", "ipa_uk": None, "ipa_us": None,
         "frequency_rank": 1, "cefr_level": "A1"},
        {"lemma": "run", "pos": "verb", "ipa_uk": None, "ipa_us": None,
         "frequency_rank": 2, "cefr_level": "A1"},
    ])
    db_manager.insert_sentences_batch([
        {"text_en": "The cat sleeps on the sofa.", "text_vi": "Con mèo ngủ trên ghế sofa.",
         "difficulty_score": 1.0, "cefr_level": "A1", "audio_path": None, "source": "TED-EnVi"},
        {"text_en": "I run every morning.", "text_vi": "Tôi chạy mỗi sáng.",
         "difficulty_score": 1.0, "cefr_level": "A1", "audio_path": None, "source": "TED-EnVi"},
    ])
    return db_manager


def test_read_checkpoint_missing_returns_zero(tmp_path):
    import main as main_module

    assert main_module._read_sentence_link_checkpoint(tmp_path / "missing.json") == 0


def test_read_checkpoint_corrupt_returns_zero(tmp_path):
    import main as main_module

    cp = tmp_path / "corrupt.json"
    cp.write_text("{not-json", encoding="utf-8")
    assert main_module._read_sentence_link_checkpoint(cp) == 0


def test_read_checkpoint_valid_returns_id(tmp_path):
    import main as main_module

    cp = tmp_path / "valid.json"
    cp.write_text(json.dumps({"last_id": 42}), encoding="utf-8")
    assert main_module._read_sentence_link_checkpoint(cp) == 42


def test_write_checkpoint_round_trip(tmp_path):
    import main as main_module

    cp = tmp_path / "roundtrip.json"
    main_module._write_sentence_link_checkpoint(cp, 7)
    assert cp.exists()
    assert main_module._read_sentence_link_checkpoint(cp) == 7


def test_force_reset_clears_stale_link_checkpoint(tmp_path, monkeypatch):
    """--force-reset must drop the checkpoint; a stale last_id would skip
    re-ingested sentences whose AUTOINCREMENT ids restart at 1."""
    import main as main_module

    cp = tmp_path / "sentence_link_checkpoint.json"
    cp.write_text(json.dumps({"last_id": 100}), encoding="utf-8")
    monkeypatch.setattr(main_module, "SENTENCE_LINK_CHECKPOINT", cp)

    main_module._clear_sentence_link_checkpoint()

    assert not cp.exists()
    assert main_module._read_sentence_link_checkpoint(cp) == 0


def test_incremental_linking_resumes_and_recovers_after_reset(tmp_path, monkeypatch):
    """4B linking: first run links + advances checkpoint, re-run is a no-op,
    and after a force-reset (wiped tables + cleared checkpoint) the recycled
    sentence ids are re-linked instead of skipped by the stale checkpoint."""
    import main as main_module

    db_manager = _make_seeded_db(tmp_path)
    cp = tmp_path / "link_cp.json"
    monkeypatch.setattr(main_module, "SENTENCE_LINK_CHECKPOINT", cp)
    conn = db_manager.get_connection()

    main_module._link_sentences_incrementally(db_manager, cp)
    first_count = conn.execute("SELECT count(*) FROM word_sentence_map").fetchone()[0]
    assert first_count >= 1
    assert main_module._read_sentence_link_checkpoint(cp) == 2

    # Idempotent: nothing new to link, checkpoint unchanged
    main_module._link_sentences_incrementally(db_manager, cp)
    assert conn.execute("SELECT count(*) FROM word_sentence_map").fetchone()[0] == first_count

    # Force reset: wipe tables (mirroring the production wipe block), clear
    # the checkpoint, re-ingest the same rows -> AUTOINCREMENT restarts at 1
    conn.execute("PRAGMA foreign_keys = OFF;")
    for tbl in ("word_sentence_map", "sentences"):
        conn.execute(f"DROP TABLE {tbl};")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON;")
    db_manager.init_schema()
    db_manager.insert_sentences_batch([
        {"text_en": "The cat sleeps on the sofa.", "text_vi": "Con mèo ngủ trên ghế sofa.",
         "difficulty_score": 1.0, "cefr_level": "A1", "audio_path": None, "source": "TED-EnVi"},
        {"text_en": "I run every morning.", "text_vi": "Tôi chạy mỗi sáng.",
         "difficulty_score": 1.0, "cefr_level": "A1", "audio_path": None, "source": "TED-EnVi"},
    ])
    recycled_ids = [r[0] for r in conn.execute("SELECT id FROM sentences ORDER BY id;").fetchall()]
    assert recycled_ids == [1, 2]

    # The fix: the checkpoint was cleared, so re-linking covers recycled ids
    main_module._clear_sentence_link_checkpoint()
    assert main_module._read_sentence_link_checkpoint(cp) == 0
    main_module._link_sentences_incrementally(db_manager, cp)
    assert conn.execute("SELECT count(*) FROM word_sentence_map").fetchone()[0] >= 1

    db_manager.close()


def test_corpus_ingest_respects_max_sentences_cap(tmp_path, monkeypatch):
    """Per-corpus cap: a giant corpus must stop at MAX_SENTENCES_PER_CORPUS
    instead of ingesting everything (guards disk space on 37M-line corpora)."""
    import main as main_module
    import config.settings as settings
    from src.db.staging_db import DatabaseManager

    en = tmp_path / "cap.en"
    vi = tmp_path / "cap.vi"
    en.write_text("\n".join(f"This is sample sentence number {i}." for i in range(12)), encoding="utf-8")
    vi.write_text("\n".join(f"Đây là câu mẫu số {i}." for i in range(12)), encoding="utf-8")

    monkeypatch.setattr(settings, "OPENSUBTITLES_EN", en)
    monkeypatch.setattr(settings, "OPENSUBTITLES_VI", vi)
    monkeypatch.setattr(settings, "ENVICORPORA_TED_LIKE_EN", tmp_path / "missing.en")
    monkeypatch.setattr(settings, "ENVICORPORA_TED_LIKE_VI", tmp_path / "missing.vi")
    monkeypatch.setattr(settings, "ENVICORPORA_BASIC_EN", tmp_path / "missing.en")
    monkeypatch.setattr(settings, "ENVICORPORA_BASIC_VI", tmp_path / "missing.vi")
    monkeypatch.setattr(settings, "MAX_SENTENCES_PER_CORPUS", 5)

    db_manager = DatabaseManager(db_path=tmp_path / "capped.db")
    db_manager.init_schema()
    args = SimpleNamespace(force_reset=False)

    stats = main_module.run_sentence_coverage_step(db_manager, args)

    assert stats["inserted"] == 5
    conn = db_manager.get_connection()
    assert conn.execute("SELECT count(*) FROM sentences").fetchone()[0] == 5
    db_manager.close()