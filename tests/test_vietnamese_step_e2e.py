# tests/test_vietnamese_step_e2e.py
import pytest
from unittest.mock import MagicMock
from main import run_vietnamese_step

def test_run_vietnamese_step_hybrid(monkeypatch):
    db_manager = MagicMock()
    conn = MagicMock()
    cursor = MagicMock()
    db_manager.get_connection.return_value = conn
    conn.cursor.return_value = cursor
    cursor.fetchall.return_value = []
    
    args = MagicMock()
    args.force_reset = False
    args.vi_budget = 100
    
    monkeypatch.setattr("main.OfflineGlossExtractor._load_glosses", lambda self: None)
    monkeypatch.setattr("main.OfflineGlossExtractor.backfill_db_glosses", lambda self, db: {"definitions": 5, "collocations": 0, "phrases": 0})
    stats = run_vietnamese_step(db_manager, args)
    assert stats["definitions"] >= 5
