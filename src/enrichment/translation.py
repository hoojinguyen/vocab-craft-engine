"""Hybrid Translation Engine: Cache -> Argos (offline) -> Google (fallback)."""

import logging
from src.db.duckdb_manager import DuckDBManager
from src.enrichment.vi_validator import VietnameseValidator

logger = logging.getLogger(__name__)


class HybridTranslator:
    def __init__(self, db_mgr: DuckDBManager):
        self.db_mgr = db_mgr
        self.validator = VietnameseValidator()

    def translate_text(self, text: str) -> str:
        if not text:
            return ""

        # 1. Cache lookup
        cached = self.db_mgr.get_translation(text)
        if cached:
            return cached

        # 2. Argos Translate offline primary
        translated = None
        try:
            import argostranslate.translate
            translated = argostranslate.translate.translate(text, "en", "vi")
        except Exception:
            pass

        if not self.validator.validate(translated):
            # 3. Google Translate fallback
            try:
                from deep_translator import GoogleTranslator
                translated = GoogleTranslator(source="en", target="vi").translate(text)
            except Exception:
                translated = f"[VI] {text}"

        final_text = translated if translated else text
        self.db_mgr.save_translation(text, final_text, translator="hybrid")
        return final_text

    def translate_definitions(self) -> int:
        conn = self.db_mgr.get_connection()
        rows = conn.execute("SELECT id, definition_en FROM definitions WHERE definition_vi IS NULL").fetchall()

        count = 0
        for def_id, def_en in rows:
            if def_en:
                vi_text = self.translate_text(def_en)
                conn.execute("UPDATE definitions SET definition_vi = ? WHERE id = ?", [vi_text, def_id])
                count += 1
        return count
