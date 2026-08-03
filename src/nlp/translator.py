"""
Automatic Vietnamese Translator for English Dataset System Engine.
Translates collocations and definition glosses into Vietnamese with local JSON caching.
"""

import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from config.settings import PROCESSED_DATA_DIR
from src.nlp.vi_validator import VietnameseTextValidator

logger = logging.getLogger(__name__)

CACHE_FILE = PROCESSED_DATA_DIR / "translation_cache.json"


class Translator:
    """Translates English phrases and definitions to Vietnamese with file caching."""

    MAX_ATTEMPTS = 2  # one initial call + one retry

    def __init__(self, cache_path: Path = CACHE_FILE, backoff_seconds: float = 0.5):
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.backoff_seconds = backoff_seconds
        self.validator = VietnameseTextValidator()
        self.cache: Dict[str, str] = self._load_cache()
        self._translator = None

    def _get_translator(self):
        if self._translator is None:
            try:
                from deep_translator import GoogleTranslator
                self._translator = GoogleTranslator(source="en", target="vi")
            except Exception as e:
                logger.warning("Could not initialize GoogleTranslator: %s", e)
        return self._translator

    def _load_cache(self) -> Dict[str, str]:
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return {
                    key: value for key, value in data.items()
                    if isinstance(value, str) and self.validator.is_vietnamese(value)
                }
            except Exception:
                return {}
        return {}

    def save_cache(self):
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Failed to save translation cache: %s", e)

    def translate_text(self, text: str) -> str:
        """
        Translates text to Vietnamese, validated by VietnameseTextValidator.
        Returns "" (never English passthrough) on failure or invalid output.
        """
        clean_text = text.strip()
        if not clean_text:
            return ""
        if clean_text in self.cache:
            return self.cache[clean_text]

        t = self._get_translator()
        if t:
            for attempt in range(self.MAX_ATTEMPTS):
                try:
                    translated = t.translate(clean_text)
                    if translated and self.validator.is_vietnamese(translated):
                        self.cache[clean_text] = translated
                        return translated
                except Exception as e:
                    logger.debug("Translation attempt %s failed for '%s': %s",
                                 attempt + 1, clean_text[:30], e)
                if attempt < self.MAX_ATTEMPTS - 1:
                    time.sleep(self.backoff_seconds)

        return ""

    def translate_collocations_batch(self, collocations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Translates phrases in collocations batch.
        """
        updated = 0
        for item in collocations:
            phrase = item.get("phrase", "")
            if not item.get("meaning_vi") or item["meaning_vi"] == phrase:
                translated = self.translate_text(phrase)
                item["meaning_vi"] = translated
                updated += 1

        if updated > 0:
            self.save_cache()

        return collocations
