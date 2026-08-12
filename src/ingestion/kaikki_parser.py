"""
Kaikki JSON Dictionary Parser for English Dataset System Engine.
Streams entries from Kaikki.org dictionary dumps (JSON list or JSONL) with low memory usage.
"""

import json
import logging
import re
from pathlib import Path
from typing import Iterator, Dict, Any, Optional, List, Set
import ijson

from src.nlp.topic_mapper import TopicMapper

logger = logging.getLogger(__name__)

CLEAN_CHARS_PATTERN = re.compile(r"^[a-zA-Z '.-]+$")
MAX_TARGETS_PER_RELATION = 25



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
        word = (item.get("word") or "").strip()
        if not word or " " in word:  # Filter out multi-word phrases from words table
            return None

        pos = (item.get("pos") or "noun").strip()

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
                    vi_word = (trans.get("word") or "").strip()
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
                    "definition_vi": vi_trans_str,
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

    def parse_stream_unified(self) -> Iterator[Dict[str, Any]]:
        """
        Yields parsed unified records containing lemma, pos, ipa_uk, ipa_us,
        definitions, relations, and topics in a single streaming pass.
        """
        for item in self.parse_raw_items():
            parsed = self.extract_fields_unified(item)
            if parsed:
                yield parsed

    @staticmethod
    def extract_fields_unified(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Extracts lemma, POS, IPA (UK/US), definitions, relations, and topics in a single pass.
        Reuses extract_fields for base word/definition parsing.
        """
        base = KaikkiParser.extract_fields(item)
        if not base:
            return None

        word = base["lemma"]
        senses = item.get("senses", []) or []

        # Extract relations (synonyms, antonyms, hypernyms, hyponyms)
        relations: List[Dict[str, str]] = []
        seen_rel: Set[tuple] = set()

        if "relations" in item and isinstance(item["relations"], list):
            for rel in item["relations"]:
                target = None
                rel_type = "synonym"
                if isinstance(rel, dict):
                    rel_type = (rel.get("type") or rel.get("relation_type") or "synonym").strip()
                    target = (rel.get("word") or rel.get("target") or rel.get("target_text") or "").strip().lower()
                elif isinstance(rel, str):
                    target = rel.strip().lower()

                if not target or target == word:
                    continue
                if len(target) == 1 or not CLEAN_CHARS_PATTERN.match(target):
                    continue

                count_for_type = sum(1 for r in relations if r["relation_type"] == rel_type)
                if count_for_type >= MAX_TARGETS_PER_RELATION:
                    continue

                key = (rel_type, target)
                if key not in seen_rel:
                    seen_rel.add(key)
                    relations.append({"relation_type": rel_type, "target": target, "source": "relations"})

        for section, rel_type in (("synonyms", "synonym"), ("antonyms", "antonym"),
                                  ("hypernyms", "hypernym"), ("hyponyms", "hyponym")):
            candidates = list(item.get(section, []) or [])
            for sense in senses:
                if isinstance(sense, dict):
                    candidates.extend(sense.get(section, []) or [])
            count_for_type = sum(1 for r in relations if r["relation_type"] == rel_type)
            for rel in candidates:
                if count_for_type >= MAX_TARGETS_PER_RELATION:
                    break
                target = None
                if isinstance(rel, dict):
                    target = (rel.get("word") or rel.get("target") or "").strip().lower()
                elif isinstance(rel, str):
                    target = rel.strip().lower()

                if not target or target == word:
                    continue
                if len(target) == 1 or not CLEAN_CHARS_PATTERN.match(target):
                    continue
                key = (rel_type, target)
                if key not in seen_rel:
                    seen_rel.add(key)
                    relations.append({"relation_type": rel_type, "target": target, "source": section})
                    count_for_type += 1

        # Extract topics
        topics: List[Dict[str, str]] = []
        seen_topics: Set[str] = set()

        raw_topics = []
        if "topics" in item and isinstance(item["topics"], list):
            raw_topics.extend(item["topics"])
        for sense in senses:
            if isinstance(sense, dict):
                raw_topics.extend(sense.get("topics", []) or [])

        for raw in raw_topics:
            if isinstance(raw, str):
                raw_label = raw.strip()
            elif isinstance(raw, dict):
                raw_label = (raw.get("topic") or raw.get("name") or "").strip()
            else:
                continue
            if not raw_label:
                continue
            key = raw_label.lower()
            if key not in seen_topics:
                seen_topics.add(key)
                mapped = TopicMapper.map_topic(raw_label)
                topics.append({"topic": mapped, "raw_topic": raw_label})

        return {
            **base,
            "relations": relations,
            "topics": topics,
        }

