"""
Kaikki JSON Dictionary Parser for English Dataset System Engine.
Streams entries from Kaikki.org dictionary dumps (JSON list or JSONL) with low memory usage.
"""

import json
import logging
from pathlib import Path
from typing import Iterator, Dict, Any, Optional, List
import ijson

logger = logging.getLogger(__name__)


class KaikkiParser:
    """Parses Wiktionary data extracted by Kaikki.org."""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)

    def parse_stream(self) -> Iterator[Dict[str, Any]]:
        """
        Yields parsed dictionary items containing word, pos, ipa, and definitions.
        Detects JSON Lines vs JSON array automatically.
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"Kaikki dump not found at {self.file_path}")

        # Check first line to detect format
        with open(self.file_path, "r", encoding="utf-8") as f:
            first_char = f.read(1).strip()

        if first_char == "[":
            # Standard JSON Array format
            yield from self._parse_json_array()
        else:
            # JSON Lines (JSONL) format
            yield from self._parse_json_lines()

    def _parse_json_array(self) -> Iterator[Dict[str, Any]]:
        with open(self.file_path, "rb") as f:
            for item in ijson.items(f, "item"):
                parsed = self.extract_fields(item)
                if parsed:
                    yield parsed

    def _parse_json_lines(self) -> Iterator[Dict[str, Any]]:
        with open(self.file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                    parsed = self.extract_fields(item)
                    if parsed:
                        yield parsed
                except json.JSONDecodeError:
                    continue

    def parse_raw_items(self) -> Iterator[Dict[str, Any]]:
        """
        Yields raw (unfiltered) dictionary items, detecting JSON Lines vs JSON array.
        Used by consumers that need multi-word entries (e.g. PhraseParser).
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"Kaikki dump not found at {self.file_path}")

        with open(self.file_path, "r", encoding="utf-8") as f:
            first_char = f.read(1).strip()

        if first_char == "[":
            with open(self.file_path, "rb") as f:
                for item in ijson.items(f, "item"):
                    if isinstance(item, dict):
                        yield item
        else:
            with open(self.file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                        if isinstance(item, dict):
                            yield item
                    except json.JSONDecodeError:
                        continue

    @staticmethod
    def extract_fields(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extracts lemma, POS, IPA (UK/US), and senses/definitions.
        """
        word = item.get("word", "").strip()
        if not word or " " in word:  # Filter out multi-word phrases from words table
            return None

        pos = item.get("pos", "noun").strip()

        # Extract IPA transcriptions
        ipa_uk = None
        ipa_us = None
        sounds = item.get("sounds", [])
        for sound in sounds:
            ipa = sound.get("ipa")
            if not ipa:
                continue
            tags = sound.get("tags", [])
            if "UK" in tags or "British" in tags:
                ipa_uk = ipa
            elif "US" in tags or "American" in tags:
                ipa_us = ipa
            elif ipa_uk is None and ipa_us is None:
                ipa_uk = ipa
                ipa_us = ipa

        # Extract Vietnamese translations if available
        vi_translations = []
        translations = item.get("translations", [])
        for trans in translations:
            if isinstance(trans, dict):
                lang_code = trans.get("code") or trans.get("lang_code")
                lang_name = trans.get("lang")
                if lang_code == "vi" or lang_name == "Vietnamese":
                    vi_word = trans.get("word", "").strip()
                    if vi_word and vi_word not in vi_translations:
                        vi_translations.append(vi_word)

        vi_trans_str = ", ".join(vi_translations) if vi_translations else None

        # Extract senses / definitions
        senses = item.get("senses", [])
        definitions = []
        for sense in senses:
            glosses = sense.get("glosses", []) or sense.get("raw_glosses", [])
            examples = sense.get("examples", [])
            example_text = None
            if examples and isinstance(examples, list):
                first_ex = examples[0]
                if isinstance(first_ex, dict):
                    example_text = first_ex.get("text")
                elif isinstance(first_ex, str):
                    example_text = first_ex

            for gloss in glosses:
                definitions.append({
                    "definition_en": gloss.strip(),
                    "definition_vi": vi_trans_str or gloss.strip(),
                    "example": example_text,
                    "source": "Kaikki/Wiktionary"
                })

        return {
            "lemma": word.lower(),
            "pos": pos.lower(),
            "ipa_uk": ipa_uk,
            "ipa_us": ipa_us,
            "vi_translations": vi_trans_str,
            "definitions": definitions
        }
