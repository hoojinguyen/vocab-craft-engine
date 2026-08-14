import pytest
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.transform.phrase_extractor import PhraseExtractor
from src.pipeline.steps.transform_phrases import TransformPhrasesStep


@pytest.fixture
def db_mgr(tmp_path: Path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    yield mgr
    mgr.close()


def test_phrase_extractor_comprehensive(db_mgr: DuckDBManager):
    db_mgr.insert_batch_fast("sentences", [
        {"text_en": "You should never give up on your dreams.", "text_vi": "Bạn không bao giờ nên từ bỏ ước mơ của mình.", "source": "tatoeba"},
        {"text_en": "Good luck tonight, break a leg!", "text_vi": "Chúc may mắn tối nay, diễn tốt nhé!", "source": "tatoeba"},
        {"text_en": "Better late than never is a great saying.", "text_vi": "Muộn còn hơn không là một câu tục ngữ tuyệt vời.", "source": "tatoeba"},
        {"text_en": "He made a strong decision to take care of his family.", "text_vi": "Anh ấy đã đưa ra một quyết định mạnh mẽ để chăm sóc gia đình.", "source": "tatoeba"},
    ])

    extractor = PhraseExtractor()
    count = extractor.extract(db_mgr)
    assert count >= 3

    conn = db_mgr.get_connection()
    phrases = conn.execute("SELECT id, phrase, phrase_type FROM phrases").fetchall()
    assert len(phrases) >= 3

    types = {p[2] for p in phrases}
    assert "phrasal_verb" in types or "idiom" in types

    # Verify foreign key integrity in phrase_sentences
    links = conn.execute("SELECT phrase_id, sentence_id FROM phrase_sentences").fetchall()
    assert len(links) >= 3
    for pid, sid in links:
        p_row = conn.execute("SELECT id FROM phrases WHERE id = ?", [pid]).fetchone()
        assert p_row is not None, f"phrase_id {pid} does not exist in phrases table!"
        s_row = conn.execute("SELECT id FROM sentences WHERE id = ?", [sid]).fetchone()
        assert s_row is not None, f"sentence_id {sid} does not exist in sentences table!"


def test_transform_phrases_step():
    step = TransformPhrasesStep()
    assert step.name == "transform_phrases"
    assert "sentences" in step.depends_on or "ingest_tatoeba" in step.depends_on
    assert "phrases" in step.produces
    assert "phrase_sentences" in step.produces
