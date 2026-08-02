"""
Tatoeba Aligned Parallel Corpus Parser for English Dataset System Engine.
Joins English and Vietnamese aligned sentences from Tatoeba export files.
"""

import csv
import logging
from pathlib import Path
from typing import Iterator, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class TatoebaParser:
    """Parses aligned English-Vietnamese sentence pairs from Tatoeba dumps."""

    def __init__(self, sentences_path: Path, links_path: Path):
        self.sentences_path = Path(sentences_path)
        self.links_path = Path(links_path)

    def parse_aligned_pairs(self) -> Iterator[Dict[str, Any]]:
        """
        Loads sentences and links, yielding clean aligned pairs.
        """
        if not self.sentences_path.exists() or not self.links_path.exists():
            raise FileNotFoundError("Tatoeba CSV files not found.")

        # 1. Load English and Vietnamese sentences into memory dicts
        eng_sentences: Dict[int, str] = {}
        vie_sentences: Dict[int, str] = {}

        logger.info("Reading Tatoeba sentences from %s", self.sentences_path)
        with open(self.sentences_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")
            for row in reader:
                if len(row) < 3:
                    continue
                try:
                    s_id = int(row[0])
                    lang = row[1].strip()
                    text = row[2].strip()

                    if lang == "eng":
                        if self._is_clean_sentence(text):
                            eng_sentences[s_id] = text
                    elif lang == "vie":
                        if text:
                            vie_sentences[s_id] = text
                except (ValueError, IndexError):
                    continue

        logger.info("Loaded %d English and %d Vietnamese sentences", len(eng_sentences), len(vie_sentences))

        # 2. Join using links
        logger.info("Joining sentence pairs via links from %s", self.links_path)
        seen_pairs = set()

        with open(self.links_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")
            for row in reader:
                if len(row) < 2:
                    continue
                try:
                    id1, id2 = int(row[0]), int(row[1])

                    # Pair 1: id1 = English, id2 = Vietnamese
                    text_en = eng_sentences.get(id1)
                    text_vi = vie_sentences.get(id2)

                    if not text_en or not text_vi:
                        # Pair 2: id2 = English, id1 = Vietnamese
                        text_en = eng_sentences.get(id2)
                        text_vi = vie_sentences.get(id1)

                    if text_en and text_vi:
                        pair_key = (text_en, text_vi)
                        if pair_key not in seen_pairs:
                            seen_pairs.add(pair_key)
                            yield {
                                "text_en": text_en,
                                "text_vi": text_vi,
                                "source": "Tatoeba"
                            }
                except (ValueError, IndexError):
                    continue

    @staticmethod
    def _is_clean_sentence(text: str) -> bool:
        """Filtering rules for clean, natural conversational sentences."""
        words = text.split()
        if len(words) < 2 or len(words) > 30:
            return False
        # Filter non-ASCII heavy or garbled text
        if not text[0].isalnum() and text[0] not in ('"', "'"):
            return False
        return True
