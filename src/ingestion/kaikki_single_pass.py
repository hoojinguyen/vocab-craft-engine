"""Single-pass Kaikki parser — reads dump once, classifies all entry types."""

import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Iterator, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

PHRASE_POS_ALLOWED = {"idiom", "phrasal verb", "proverb", "phrase"}
MAX_WORDS_PER_PHRASE = 6
CLEAN_CHARS_PATTERN = re.compile(r"^[a-zA-Z '.-]+$")


@dataclass
class ParseResult:
    """Holds all parsed entities from a single Kaikki pass."""
    words: List[Dict[str, Any]] = field(default_factory=list)
    definitions: List[Dict[str, Any]] = field(default_factory=list)
    phrases: List[Dict[str, Any]] = field(default_factory=list)
    relations: List[Dict[str, Any]] = field(default_factory=list)
    topics: List[Dict[str, Any]] = field(default_factory=list)


class KaikkiSinglePassParser:
    """Streams Kaikki dump once, yielding categorized entries.

    For each JSON entry, classifies into:
    - word (single-word, goes to words table)
    - phrase (multi-word expression with allowed POS)
    - relations (synonyms, antonyms, hypernyms, hyponyms)
    - topics (sense-level topics)
    - definitions (for words)
    """

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)

    def parse_all(self, max_entries: Optional[int] = None) -> ParseResult:
        result = ParseResult()
        for i, item in self._stream_jsonl():
            if max_entries and i >= max_entries:
                break
            self._classify(item, result)
        logger.info(
            "Single-pass complete: %d words, %d definitions, %d phrases, %d relations, %d topics",
            len(result.words), len(result.definitions), len(result.phrases),
            len(result.relations), len(result.topics),
        )
        return result

    def parse_stream(self, batch_size: int = 5000) -> Iterator[Tuple[str, List[Dict]]]:
        """Stream batches of categorized entries for memory-efficient processing."""
        batch: Dict[str, List[Dict]] = {
            "word": [], "phrase": [], "relation": [], "topic": [], "definition": []
        }
        for _, item in self._stream_jsonl():
            self._classify_to_dict(item, batch)
            if len(batch["word"]) >= batch_size:
                for category, rows in batch.items():
                    if rows:
                        yield category, rows
                batch = {k: [] for k in batch}

        for category, rows in batch.items():
            if rows:
                yield category, rows

    def _stream_jsonl(self) -> Iterator[Tuple[int, Dict]]:
        if not self.file_path.exists():
            raise FileNotFoundError(f"Kaikki dump not found: {self.file_path}")
        with open(self.file_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield i, json.loads(line)
                except json.JSONDecodeError:
                    continue

    def _classify(self, item: Dict, result: ParseResult):
        word = (item.get("word") or "").strip()
        if not word:
            return
        pos = (item.get("pos") or "").strip().lower()
        is_phrase = " " in word and pos in PHRASE_POS_ALLOWED

        if is_phrase:
            parsed = self._extract_phrase(word, pos, item)
            if parsed:
                result.phrases.append(parsed)
            return

        parsed_word = self._extract_word(word, pos, item)
        if parsed_word:
            result.words.append(parsed_word)

        result.definitions.extend(self._extract_definitions(word, item))
        result.relations.extend(self._extract_relations(word, item))
        result.topics.extend(self._extract_topics(word, item))

    def _classify_to_dict(self, item: Dict, batch: Dict[str, List[Dict]]):
        word = (item.get("word") or "").strip()
        if not word:
            return
        pos = (item.get("pos") or "").strip().lower()
        is_phrase = " " in word and pos in PHRASE_POS_ALLOWED

        if is_phrase:
            parsed = self._extract_phrase(word, pos, item)
            if parsed:
                batch["phrase"].append(parsed)
            return

        parsed_word = self._extract_word(word, pos, item)
        if parsed_word:
            batch["word"].append(parsed_word)
        for d in self._extract_definitions(word, item):
            batch["definition"].append(d)
        for r in self._extract_relations(word, item):
            batch["relation"].append(r)
        for t in self._extract_topics(word, item):
            batch["topic"].append(t)

    def _extract_word(self, word: str, pos: str, item: Dict) -> Optional[Dict]:
        word_clean = word.strip().lower()
        if " " in word_clean:
            return None
        ipa_uk, ipa_us = self._extract_ipas(item)
        vi = self._extract_vi_translations(item)
        return {
            "lemma": word_clean,
            "pos": pos,
            "ipa_uk": ipa_uk,
            "ipa_us": ipa_us,
            "vi_translations": vi,
        }

    def _extract_phrase(self, word: str, pos: str, item: Dict) -> Optional[Dict]:
        word_clean = word.strip().lower()
        if " " not in word_clean:
            return None
        if len(word_clean.split()) > MAX_WORDS_PER_PHRASE and pos != "proverb":
            return None
        if not CLEAN_CHARS_PATTERN.match(word_clean):
            return None

        ipa = None
        for sound in item.get("sounds", []):
            if sound.get("ipa"):
                ipa = sound["ipa"]
                break

        vi = self._extract_vi_translations(item)

        definition_en = None
        for sense in item.get("senses", []):
            glosses = sense.get("glosses", []) or sense.get("raw_glosses", [])
            for gloss in glosses:
                if gloss.strip():
                    definition_en = gloss.strip()
                    break
            if definition_en:
                break

        if not definition_en:
            return None

        return {
            "phrase": word_clean,
            "phrase_type": pos.replace(" ", "_"),
            "pos": pos,
            "definition_en": definition_en,
            "definition_vi": vi,
            "ipa": ipa,
        }

    def _extract_definitions(self, word: str, item: Dict) -> List[Dict]:
        results = []
        vi = self._extract_vi_translations(item)
        for sense in item.get("senses", []):
            glosses = sense.get("glosses", []) or sense.get("raw_glosses", []) or []
            example = None
            for ex in sense.get("examples", []) or []:
                if isinstance(ex, dict):
                    example = ex.get("text")
                elif isinstance(ex, str):
                    example = ex
                if example:
                    break
            for gloss in glosses:
                if not isinstance(gloss, str):
                    continue
                results.append({
                    "lemma": word.lower(),
                    "definition_en": gloss.strip(),
                    "definition_vi": vi,
                    "example": example,
                    "source": "Kaikki/Wiktionary",
                })
        return results

    def _extract_relations(self, word: str, item: Dict) -> List[Dict]:
        results = []
        word_lower = word.lower()
        seen = set()

        for section, rel_type in [
            ("synonyms", "synonym"), ("antonyms", "antonym"),
            ("hypernyms", "hypernym"), ("hyponyms", "hyponym"),
        ]:
            candidates = list(item.get(section, []) or [])
            for sense in item.get("senses", []):
                candidates.extend(sense.get(section, []) or [])

            count = 0
            for rel in candidates:
                if count >= 25:
                    break
                if not isinstance(rel, dict):
                    continue
                target = (rel.get("word") or "").strip().lower()
                if not target or target == word_lower:
                    continue
                if len(target) == 1 or not CLEAN_CHARS_PATTERN.match(target):
                    continue
                key = (rel_type, target)
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "lemma": word_lower,
                    "relation_type": rel_type,
                    "target_text": target,
                    "source": section,
                })
                count += 1
        return results

    def _extract_topics(self, word: str, item: Dict) -> List[Dict]:
        results = []
        seen = set()
        for sense in item.get("senses", []):
            for raw in sense.get("topics", []) or []:
                raw_label = (raw or "").strip()
                if not raw_label:
                    continue
                key = raw_label.lower()
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    "lemma": word.lower(),
                    "raw_topic": raw_label,
                })
        return results

    @staticmethod
    def _extract_ipas(item: Dict) -> Tuple[Optional[str], Optional[str]]:
        ipa_uk, ipa_us = None, None
        for sound in item.get("sounds", []):
            ipa = sound.get("ipa")
            if not ipa:
                continue
            tags = sound.get("tags", [])
            if "UK" in tags or "British" in tags:
                ipa_uk = ipa
            elif "US" in tags or "American" in tags:
                ipa_us = ipa
            elif ipa_uk is None:
                ipa_uk = ipa
                ipa_us = ipa
        return ipa_uk, ipa_us

    @staticmethod
    def _extract_vi_translations(item: Dict) -> Optional[str]:
        vi_translations = []
        for trans in item.get("translations", []):
            if isinstance(trans, dict):
                code = trans.get("code") or trans.get("lang_code")
                lang = trans.get("lang")
                if code == "vi" or lang == "Vietnamese":
                    w = trans.get("word", "").strip()
                    if w and w not in vi_translations:
                        vi_translations.append(w)
        return ", ".join(vi_translations) if vi_translations else None
