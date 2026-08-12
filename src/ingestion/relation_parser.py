"""
Lexical Relation & Topic Parser for English Dataset System Engine.
Extracts synonyms, antonyms, hypernyms, hyponyms and sense-level topics
from raw Kaikki dump entries (single-word entries only).

DEPRECATED: Use KaikkiSinglePassParser from src.ingestion.kikki_single_pass instead.
"""

import logging
import re
from pathlib import Path
from typing import Iterator, Dict, Any, Optional, List, Set

from src.ingestion.kaikki_parser import KaikkiParser
from src.nlp.topic_mapper import TopicMapper

logger = logging.getLogger(__name__)

# Only letters, spaces, hyphens, apostrophes and periods are allowed
CLEAN_CHARS_PATTERN = re.compile(r"^[a-zA-Z '.-]+$")

MAX_TARGETS_PER_RELATION = 25


class RelationParser:
    """Parses lexical relations and topics from Kaikki dump entries (streaming)."""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)

    @staticmethod
    def extract_entry_fields(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        word = item.get("word", "").strip().lower()
        if not word or " " in word:
            return None

        relations: List[Dict[str, str]] = []
        seen: Set[tuple] = set()
        for section, rel_type in (("synonyms", "synonym"), ("antonyms", "antonym"),
                                  ("hypernyms", "hypernym"), ("hyponyms", "hyponym")):
            candidates = list(item.get(section, []) or [])
            for sense in item.get("senses", []) or []:
                candidates.extend(sense.get(section, []) or [])
            count_for_type = 0
            for rel in candidates:
                if count_for_type >= MAX_TARGETS_PER_RELATION:
                    break
                if not isinstance(rel, dict):
                    continue
                target = (rel.get("word") or "").strip().lower()
                if not target or target == word:
                    continue
                if len(target) == 1 or not CLEAN_CHARS_PATTERN.match(target):
                    continue
                key = (rel_type, target)
                if key in seen:
                    continue
                seen.add(key)
                relations.append({"relation_type": rel_type, "target": target, "source": section})
                count_for_type += 1

        topics: List[Dict[str, str]] = []
        seen_topics: Set[str] = set()
        for sense in item.get("senses", []) or []:
            for raw in sense.get("topics", []) or []:
                raw_label = (raw or "").strip()
                if not raw_label:
                    continue
                key = raw_label.lower()
                if key in seen_topics:
                    continue
                seen_topics.add(key)
                topics.append({"topic": TopicMapper.map_topic(raw_label), "raw_topic": raw_label})

        if not relations and not topics:
            return None
        return {"word": word, "relations": relations, "topics": topics}

    def parse_entries(self) -> Iterator[Dict[str, Any]]:
        """Yields parsed single-word entry dicts: {word, relations, topics}."""
        kaikki = KaikkiParser(self.file_path)
        for item in kaikki.parse_raw_items():
            parsed = self.extract_entry_fields(item)
            if parsed:
                yield parsed
