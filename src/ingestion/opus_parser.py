"""
OPUS / OpenSubtitles Dialogue Parser for English Dataset System Engine.
Extracts short conversational dialogue utterances (2-10 words) for scenario trees.
"""

import logging
from pathlib import Path
from typing import Iterator, Dict, Any, List

logger = logging.getLogger(__name__)


class OpusParser:
    """Parses OpenSubtitles / OPUS conversational text dumps into dialogue utterances."""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)

    def parse_dialogue_lines(self) -> Iterator[Dict[str, Any]]:
        """
        Reads lines from OPUS parallel text file, yielding conversational English-Vietnamese pairs.
        Expected format: tab-separated lines "text_en \t text_vi" or plain English lines.
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"OPUS subtitles file not found at {self.file_path}")

        with open(self.file_path, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                parts = line.split("\t")
                text_en = parts[0].strip()
                text_vi = parts[1].strip() if len(parts) > 1 else ""

                if self._is_conversational_turn(text_en):
                    yield {
                        "line_id": line_idx,
                        "text_en": text_en,
                        "text_vi": text_vi,
                        "word_count": len(text_en.split()),
                        "source": "OpenSubtitles"
                    }

    @staticmethod
    def _is_conversational_turn(text: str) -> bool:
        """Filtering for conversational dialogue turns (2 to 12 words)."""
        words = text.split()
        if len(words) < 2 or len(words) > 12:
            return False

        # Ignore lines starting with musical notes, brackets, or numbers
        if text.startswith(("-", "#", "[", "(", "1", "2", "3")):
            return False

        return True
