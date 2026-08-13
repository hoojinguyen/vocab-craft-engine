import pytest
from src.db.duckdb_manager import DuckDBManager
from src.transform.phrase_extractor import PhraseExtractor
from src.pipeline.steps.transform_phrases import TransformPhrasesStep


@pytest.fixture
def db_mgr(tmp_path):
    mgr = DuckDBManager(db_path=tmp_path / "test.duckdb")
    mgr.init_schema()
    mgr.insert_batch("sentences", [{"text_en": "You need to break down the task.", "source": "tatoeba"}])
    yield mgr
    mgr.close()


def test_phrase_extractor(db_mgr):
    extractor = PhraseExtractor()
    extracted = extractor.extract(db_mgr)
    assert extracted >= 1
    assert db_mgr.count_rows("phrases") >= 1
