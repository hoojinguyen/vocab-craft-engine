"""Parallel corpus parser for OpenSubtitles / EnViCorpora side-by-side files."""

import logging
from pathlib import Path
from typing import Iterator, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ParallelCorpusParser:
    """Reads aligned en/vi parallel files (Moses format: line-aligned sides).

    Yields deduplicated pairs as {"text_en", "text_vi", "source"}.
    No filtering here — filtering happens in SentenceFilter (spec §4.3).
    """

    def __init__(self, en_path: Optional[Path] = None, vi_path: Optional[Path] = None,
                 source: str = "OpenSubtitles", tsv_path: Optional[Path] = None):
        self.en_path = Path(en_path) if en_path else None
        self.vi_path = Path(vi_path) if vi_path else None
        self.tsv_path = Path(tsv_path) if tsv_path else None
        self.source = source

    def parse_pairs(self) -> Iterator[Dict[str, Any]]:
        if self.tsv_path:
            yield from self._parse_tsv()
            return
        if not self.en_path or not self.en_path.exists() or not self.vi_path or not self.vi_path.exists():
            return
        seen: set = set()
        with open(self.en_path, "r", encoding="utf-8") as f_en, \
             open(self.vi_path, "r", encoding="utf-8") as f_vi:
            for en_line, vi_line in zip(f_en, f_vi):
                text_en = en_line.strip()
                text_vi = vi_line.strip()
                if not text_en or not text_vi:
                    continue
                key = (text_en.lower().strip(), text_vi.lower().strip())
                if key in seen:
                    continue
                seen.add(key)
                yield {"text_en": text_en, "text_vi": text_vi, "source": self.source}

    def _parse_tsv(self) -> Iterator[Dict[str, Any]]:
        seen: set = set()
        with open(self.tsv_path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) < 2:
                    continue
                text_en, text_vi = parts[0].strip(), parts[1].strip()
                if not text_en or not text_vi:
                    continue
                key = (text_en.lower(), text_vi.lower())
                if key in seen:
                    continue
                seen.add(key)
                yield {"text_en": text_en, "text_vi": text_vi, "source": self.source}


# Backward-compat alias for the old narrow reader (removed filter semantics).
OpusParser = ParallelCorpusParser