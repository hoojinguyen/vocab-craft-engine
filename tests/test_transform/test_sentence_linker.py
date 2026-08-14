import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.transform.sentence_linker import SentenceLinker
from src.pipeline.steps.transform_linking import TransformLinkingStep


@pytest.fixture
def db_mgr(tmp_path: Path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_sentence_linker_lemmatized_matching(db_mgr: DuckDBManager):
    db_mgr.insert_batch_fast("words", [
        {"lemma": "run", "pos": "verb", "source": "kaikki"},
        {"lemma": "dog", "pos": "noun", "source": "kaikki"},
        {"lemma": "fast", "pos": "adj", "source": "kaikki"},
        {"lemma": "walk", "pos": "verb", "source": "kaikki"},
    ])

    db_mgr.insert_batch_fast("sentences", [
        {"text_en": "The dogs are running very fast in the park.", "text_vi": "Những con chó đang chạy rất nhanh trong công viên.", "source": "tatoeba"},
        {"text_en": "He ran home yesterday.", "text_vi": "Anh ấy đã chạy về nhà hôm qua.", "source": "tatoeba"},
        {"text_en": "They walked slowly.", "text_vi": "Họ đã đi bộ chậm rãi.", "source": "tatoeba"},
    ])

    linker = SentenceLinker()
    linked_count = linker.link(db_mgr, batch_size=2)
    assert linked_count > 0

    conn = db_mgr.get_connection()
    links = conn.execute("""
        SELECT w.lemma, s.text_en 
        FROM word_sentences ws
        JOIN words w ON ws.word_id = w.id
        JOIN sentences s ON ws.sentence_id = s.id
        ORDER BY w.lemma, s.id
    """).fetchall()

    lemmas_linked = {row[0] for row in links}
    assert "dog" in lemmas_linked      # matched 'dogs'
    assert "run" in lemmas_linked      # matched 'running' and 'ran'
    assert "fast" in lemmas_linked     # matched 'fast'
    assert "walk" in lemmas_linked     # matched 'walked'


def test_sentence_linker_step_attributes():
    step = TransformLinkingStep()
    assert step.name == "transform_linking"
    assert "words" in step.depends_on or "ingest_kaikki" in step.depends_on
    assert "word_sentences" in step.produces
