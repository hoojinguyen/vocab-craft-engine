"""
Multi-Word Expression Parser for English Dataset System Engine.
Extracts idioms, phrasal verbs, proverbs and fixed expressions from Kaikki dump entries.
"""

import logging
import re
from pathlib import Path
from typing import Iterator, Dict, Any, Optional

from src.ingestion.kaikki_parser import KaikkiParser

logger = logging.getLogger(__name__)

PHRASE_POS_ALLOWED = {"idiom", "phrasal verb", "proverb", "phrase"}
MAX_WORDS = 6
# Only letters, spaces, hyphens, apostrophes and periods are allowed
CLEAN_CHARS_PATTERN = re.compile(r"^[a-zA-Z '.-]+$")


class PhraseParser:
    """Parses multi-word expressions from Kaikki dump entries (streaming)."""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)

    @staticmethod
    def extract_phrase_fields(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        word = item.get("word", "").strip().lower()
        if not word or " " not in word:
            return None

        pos = item.get("pos", "").strip().lower()
        if pos not in PHRASE_POS_ALLOWED:
            return None

        if len(word.split()) > MAX_WORDS and pos != "proverb":
            return None

        # Quality filter: reject digits and special characters
        if not CLEAN_CHARS_PATTERN.match(word):
            return None

        # Extract first IPA transcription
        ipa = None
        for sound in item.get("sounds", []):
            sound_ipa = sound.get("ipa")
            if sound_ipa:
                ipa = sound_ipa
                break

        # Extract Vietnamese translations
        vi_translations = []
        for trans in item.get("translations", []):
            if isinstance(trans, dict):
                lang_code = trans.get("code") or trans.get("lang_code")
                lang_name = trans.get("lang")
                if lang_code == "vi" or lang_name == "Vietnamese":
                    vi_word = trans.get("word", "").strip()
                    if vi_word and vi_word not in vi_translations:
                        vi_translations.append(vi_word)
        vi_trans_str = ", ".join(vi_translations) if vi_translations else None

        # Extract first definition gloss
        definition_en = None
        for sense in item.get("senses", []):
            glosses = sense.get("glosses", []) or sense.get("raw_glosses", [])
            for gloss in glosses:
                gloss_text = gloss.strip()
                if gloss_text:
                    definition_en = gloss_text
                    break
            if definition_en:
                break

        if not definition_en:
            return None

        return {
            "phrase": word,
            "phrase_type": pos.replace(" ", "_"),
            "pos": pos,
            "definition_en": definition_en,
            "definition_vi": vi_trans_str,
            "ipa": ipa
        }

    def parse_phrases(self) -> Iterator[Dict[str, Any]]:
        """Yields parsed multi-word expression dicts."""
        kaikki = KaikkiParser(self.file_path)
        for item in kaikki.parse_raw_items():
            parsed = self.extract_phrase_fields(item)
            if parsed:
                yield parsed
