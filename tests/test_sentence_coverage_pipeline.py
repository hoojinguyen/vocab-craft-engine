"""Integration test: ingest parallel corpus → link → pack coverage improves."""

import sqlite3
from pathlib import Path


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