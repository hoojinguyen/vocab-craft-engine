import json
import logging
from pathlib import Path
from typing import Dict, Optional

from src.nlp.vi_validator import VietnameseTextValidator

logger = logging.getLogger(__name__)


class OfflineGlossExtractor:
    """Extracts Vietnamese translations from Kaikki raw JSON dumps into a fast in-memory map."""

    _CACHE: Dict[Path, Dict[str, str]] = {}

    def __init__(self, kaikki_path: Path):
        self.kaikki_path = Path(kaikki_path)
        self.validator = VietnameseTextValidator()
        self.gloss_map: Dict[str, str] = {}
        self._load_glosses()

    def _load_glosses(self) -> None:
        if self.kaikki_path in self._CACHE:
            self.gloss_map = self._CACHE[self.kaikki_path]
            return

        if not self.kaikki_path.exists():
            logger.warning(
                "Kaikki path %s does not exist for offline gloss extraction.",
                self.kaikki_path,
            )
            return

        count = 0
        try:
            with open(self.kaikki_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("lang_code") == "vi":
                            word_val = data.get("word")
                            if not word_val or not isinstance(word_val, str):
                                continue
                            word = word_val.strip().lower()
                            if not word:
                                continue
                            senses = data.get("senses", [])
                            for sense in senses:
                                glosses = sense.get("glosses", [])
                                if glosses and isinstance(glosses[0], str):
                                    g_text = glosses[0].strip()
                                    if g_text and self.validator.is_vietnamese(g_text):
                                        self.gloss_map[word] = g_text
                                        count += 1
                                        break
                    except Exception:
                        continue
            logger.info(
                "Loaded %d offline Vietnamese glosses from Kaikki dump.", count
            )
            self._CACHE[self.kaikki_path] = self.gloss_map
        except Exception as e:
            logger.warning("Error reading Kaikki dump for offline glosses: %s", e)

    def get_translation(self, text: str) -> Optional[str]:
        if not text:
            return None
        clean = text.strip().lower()
        return self.gloss_map.get(clean)

    def backfill_db_glosses(self, db_manager) -> Dict[str, int]:
        conn = db_manager.get_connection()
        cursor = conn.cursor()

        # Backfill definitions
        cursor.execute(
            "SELECT d.id, w.lemma FROM definitions d JOIN words w ON w.id = d.word_id WHERE d.definition_vi IS NULL OR d.definition_vi = '';"
        )
        def_rows = cursor.fetchall()
        def_updates = [
            (self.gloss_map[w.lower()], d_id)
            for d_id, w in def_rows
            if w and w.lower() in self.gloss_map
        ]
        if def_updates:
            cursor.executemany(
                "UPDATE definitions SET definition_vi = ? WHERE id = ?;",
                def_updates,
            )

        # Backfill collocations
        cursor.execute(
            "SELECT id, phrase FROM collocations WHERE meaning_vi IS NULL OR meaning_vi = '';"
        )
        col_rows = cursor.fetchall()
        col_updates = [
            (self.gloss_map[p.lower()], c_id)
            for c_id, p in col_rows
            if p and p.lower() in self.gloss_map
        ]
        if col_updates:
            cursor.executemany(
                "UPDATE collocations SET meaning_vi = ? WHERE id = ?;",
                col_updates,
            )

        # Backfill phrases
        cursor.execute(
            "SELECT id, phrase FROM phrases WHERE definition_vi IS NULL OR definition_vi = '';"
        )
        phr_rows = cursor.fetchall()
        phr_updates = [
            (self.gloss_map[p.lower()], p_id)
            for p_id, p in phr_rows
            if p and p.lower() in self.gloss_map
        ]
        if phr_updates:
            cursor.executemany(
                "UPDATE phrases SET definition_vi = ? WHERE id = ?;",
                phr_updates,
            )

        conn.commit()
        return {
            "definitions": len(def_updates),
            "collocations": len(col_updates),
            "phrases": len(phr_updates),
        }
