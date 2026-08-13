"""Reflex Drill Exercise Generator."""

import json
from src.db.duckdb_manager import DuckDBManager


class ReflexBuilder:
    def build(self, db_mgr: DuckDBManager) -> int:
        conn = db_mgr.get_connection()
        sentences = conn.execute("SELECT id, text_en, text_vi FROM sentences").fetchall()

        batch = []
        for sid, text_en, text_vi in sentences:
            batch.append({
                "sentence_id": sid,
                "drill_type": "cloze",
                "prompt_text": f"Fill in missing word: {text_en}",
                "correct_answer": text_en.split()[0] if text_en.split() else "run",
                "distractors_json": json.dumps(["walk", "jump", "fly"]),
                "target_time_ms": 2500,
            })

        if batch:
            return db_mgr.insert_batch("reflex_drills", batch)
        return 0
