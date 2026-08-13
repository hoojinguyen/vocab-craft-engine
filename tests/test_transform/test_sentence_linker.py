import pytest
from src.db.duckdb_manager import DuckDBManager
from src.transform.sentence_linker import SentenceLinker
from src.pipeline.steps.transform_linking import TransformLinkingStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    mgr.insert_batch("words", [{"lemma": "run", "pos": "verb", "source": "kaikki"}])
    mgr.insert_batch("sentences", [{"text_en": "The dog will run fast.", "source": "tatoeba"}])
    yield mgr
    mgr.close()


def test_sentence_linker(db_mgr):
    linker = SentenceLinker()
    linked = linker.link(db_mgr)
    assert linked == 1
    assert db_mgr.count_rows("word_sentences") == 1
