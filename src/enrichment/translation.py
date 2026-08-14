"""Hybrid Translation Engine: Cache -> Argos (offline) -> Google (fallback) with Vectorized Bulk DB Updates."""

import logging
from typing import Dict, List, Optional
import pyarrow as pa

from src.db.duckdb_manager import DuckDBManager
from src.enrichment.vi_validator import VietnameseValidator

logger = logging.getLogger(__name__)


class HybridTranslator:
    def __init__(self, db_mgr: DuckDBManager):
        self.db_mgr = db_mgr
        self.validator = VietnameseValidator()

    def translate_text(self, text: str) -> str:
        if not text or not text.strip():
            return ""

        clean_text = text.strip()

        # 1. Cache lookup
        cached = self.db_mgr.get_translation(clean_text)
        if cached:
            return cached

        # 2. Argos Translate offline primary
        translated = None
        source_engine = "argos"
        try:
            import argostranslate.translate
            translated = argostranslate.translate.translate(clean_text, "en", "vi")
        except Exception:
            pass

        if not self.validator.validate(translated):
            # 3. Google Translate fallback
            source_engine = "google"
            try:
                from deep_translator import GoogleTranslator
                translated = GoogleTranslator(source="en", target="vi").translate(clean_text)
            except Exception:
                translated = None

        if not self.validator.validate(translated):
            # Fallback placeholder if offline & network unavailable
            translated = f"[VI] {clean_text}"
            source_engine = "fallback"

        final_text = translated if translated else clean_text
        self.db_mgr.save_translation(clean_text, final_text, translator=source_engine)
        return final_text

    def translate_texts_batch(self, texts: List[str]) -> Dict[str, str]:
        if not texts:
            return {}

        results: Dict[str, str] = {}
        unique_texts = list(set(t.strip() for t in texts if t and t.strip()))

        # Check DuckDB translation cache
        cached_map = self.db_mgr.get_translations_batch(unique_texts)
        results.update(cached_map)

        # Translate missing texts
        missing = [t for t in unique_texts if t not in results]
        for item in missing:
            results[item] = self.translate_text(item)

        return results

    def translate_definitions(self, batch_size: int = 500, limit: Optional[int] = None) -> int:
        conn = self.db_mgr.get_connection()
        query = "SELECT id, definition_en FROM definitions WHERE definition_vi IS NULL AND definition_en IS NOT NULL"
        if limit:
            query += f" LIMIT {limit}"

        rows = conn.execute(query).fetchall()
        if not rows:
            logger.info("No definitions requiring translation")
            return 0

        total_translated = 0

        for i in range(0, len(rows), batch_size):
            chunk = rows[i : i + batch_size]
            en_texts = [r[1] for r in chunk if r[1]]
            trans_map = self.translate_texts_batch(en_texts)

            update_rows = []
            for def_id, def_en in chunk:
                if def_en and def_en.strip() in trans_map:
                    update_rows.append({"def_id": def_id, "vi_text": trans_map[def_en.strip()]})

            if update_rows:
                arrow_table = pa.Table.from_pylist(update_rows)
                conn.register("_tmp_def_trans", arrow_table)
                conn.execute("""
                    UPDATE definitions
                    SET definition_vi = _tmp_def_trans.vi_text
                    FROM _tmp_def_trans
                    WHERE definitions.id = _tmp_def_trans.def_id;
                """)
                conn.unregister("_tmp_def_trans")
                total_translated += len(update_rows)

        logger.info("Successfully translated and updated %d definitions", total_translated)
        return total_translated

    def translate_phrases(self, batch_size: int = 500, limit: Optional[int] = None) -> int:
        conn = self.db_mgr.get_connection()
        query = "SELECT id, phrase, definition_en FROM phrases WHERE definition_vi IS NULL"
        if limit:
            query += f" LIMIT {limit}"

        rows = conn.execute(query).fetchall()
        if not rows:
            logger.info("No phrases requiring translation")
            return 0

        total_translated = 0

        for i in range(0, len(rows), batch_size):
            chunk = rows[i : i + batch_size]
            # Prioritize translating definition_en; fallback to phrase text
            en_texts = [r[2] if r[2] else r[1] for r in chunk]
            trans_map = self.translate_texts_batch(en_texts)

            update_rows = []
            for pid, phrase_text, def_en in chunk:
                target_en = (def_en if def_en else phrase_text).strip()
                if target_en in trans_map:
                    update_rows.append({"phrase_id": pid, "vi_text": trans_map[target_en]})

            if update_rows:
                arrow_table = pa.Table.from_pylist(update_rows)
                conn.register("_tmp_phrase_trans", arrow_table)
                conn.execute("""
                    UPDATE phrases
                    SET definition_vi = _tmp_phrase_trans.vi_text
                    FROM _tmp_phrase_trans
                    WHERE phrases.id = _tmp_phrase_trans.phrase_id;
                """)
                conn.unregister("_tmp_phrase_trans")
                total_translated += len(update_rows)

        logger.info("Successfully translated and updated %d phrases", total_translated)
        return total_translated
