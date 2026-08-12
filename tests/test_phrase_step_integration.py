import pytest
from unittest.mock import MagicMock
from main import run_phrase_step

def test_run_phrase_step_fast_execution(tmp_path):
    db_manager = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    db_manager.get_connection.return_value = conn
    conn.cursor.return_value = cursor
    cursor.fetchone.side_effect = [(0,), (0,)]  # 0 existing phrases, 0 missing audio
    cursor.fetchall.return_value = [(1, "give up")]

    args = MagicMock()
    args.force_reset = False

    mock_offline_extractor = MagicMock()
    mock_offline_extractor.get_translation.return_value = "từ bỏ"

    mock_matcher = MagicMock()
    mock_matcher.match_phrases_sql.return_value = [{"phrase_id": 1, "sentence_id": 100}]

    mock_translator = MagicMock()

    with pytest.MonkeyPatch().context() as m:
        m.setattr("main.PhraseParser.parse_phrases", lambda self: [
            {"phrase": "give up", "phrase_type": "phrasal_verb", "pos": "verb", "definition_en": "stop trying"}
        ])
        m.setattr("main.OfflineGlossExtractor", lambda path: mock_offline_extractor, raising=False)
        m.setattr("main.PhraseExampleMatcher", lambda sentences: mock_matcher)
        m.setattr("main.Translator", mock_translator)
        m.setattr("main.asyncio.run", lambda coro: None)

        stats = run_phrase_step(db_manager, args)

        assert stats["phrases"] == 1
        assert stats["links"] == 1
        mock_offline_extractor.get_translation.assert_called_once_with("give up")
        mock_matcher.match_phrases_sql.assert_called_once_with(conn, [{"id": 1, "phrase": "give up"}])
        mock_translator.assert_not_called()
