"""
Hồ Ngọc Đức Free Vietnamese Dictionary Project (FVDP) Ingestion Parser.

Stream-parses the authoritative Anh-Viet dictionary (DICT / StarDict text format)
into structured headwords, Vietnamese definitions, IPA phonetics, and contextual examples.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

# POS Vietnamese mapping to standard canonical POS tags
VN_POS_MAP = {
    "danh từ": "noun",
    "ngoại động từ": "verb",
    "nội động từ": "verb",
    "động từ": "verb",
    "tính từ": "adj",
    "phó từ": "adv",
    "trạng từ": "adv",
    "giới từ": "prep",
    "liên từ": "conj",
    "thán từ": "intj",
    "đại từ": "pron",
    "cụm từ": "phrase",
    "thành ngữ": "idiom",
    "tiền tố": "prefix",
    "hậu tố": "suffix",
}


def normalize_vn_pos(raw_pos: str) -> str:
    """Maps Vietnamese POS description to canonical POS tag."""
    clean = raw_pos.strip().lower()
    for vn_name, canonical in VN_POS_MAP.items():
        if vn_name in clean:
            return canonical
    return "noun"


class FVDPParser:
    """Parses Hồ Ngọc Đức dictionary file format into normalized dictionary entries."""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)

    def parse_entries(self) -> Iterator[Dict[str, Any]]:
        """
        Streams entries from the dictionary file.
        Each yielded item has format:
        {
            "lemma": str,
            "ipa": Optional[str],
            "definitions": List[{
                "pos": str,
                "definition_vi": str,
                "definition_en": str,
                "examples": List[Dict[str, str]]
            }]
        }
        """
        if not self.file_path.exists():
            logger.warning("FVDP dictionary file not found at %s", self.file_path)
            return

        current_lemma: Optional[str] = None
        current_ipa: Optional[str] = None
        current_pos = "noun"
        current_defs: List[Dict[str, Any]] = []
        current_examples: List[Dict[str, str]] = []
        current_meaning_lines: List[str] = []

        def flush_meaning():
            nonlocal current_meaning_lines, current_examples
            if current_meaning_lines:
                meaning_text = "; ".join(current_meaning_lines).strip()
                if meaning_text:
                    current_defs.append({
                        "pos": current_pos,
                        "definition_vi": meaning_text,
                        "definition_en": f"Definition of {current_lemma} ({current_pos}): {meaning_text}",
                        "examples": list(current_examples),
                    })
                current_meaning_lines = []
                current_examples = []

        def flush_entry():
            nonlocal current_lemma, current_ipa, current_defs
            flush_meaning()
            if current_lemma and current_defs:
                entry = {
                    "lemma": current_lemma.strip().lower(),
                    "ipa": current_ipa.strip() if current_ipa else None,
                    "definitions": current_defs,
                }
                current_defs = []
                return entry
            current_defs = []
            return None

        with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue

                if line_str.startswith("@"):
                    # New headword line: @word /ipa/ or @word
                    prev_entry = flush_entry()
                    if prev_entry:
                        yield prev_entry

                    header = line_str[1:].strip()
                    ipa_match = re.search(r"/(.+?)/", header)
                    if ipa_match:
                        current_ipa = f"/{ipa_match.group(1).strip()}/"
                        current_lemma = header[: ipa_match.start()].strip()
                    else:
                        current_ipa = None
                        current_lemma = header
                    current_pos = "noun"

                elif line_str.startswith("*"):
                    # POS header: *  danh từ / *  ngoại động từ
                    flush_meaning()
                    pos_text = line_str[1:].strip()
                    current_pos = normalize_vn_pos(pos_text)

                elif line_str.startswith("-"):
                    # Meaning definition: - từ bỏ; buông thả
                    meaning = line_str[1:].strip()
                    if meaning:
                        current_meaning_lines.append(meaning)

                elif line_str.startswith("="):
                    # Example line: =to abandon a habit+từ bỏ một thói quen
                    example_raw = line_str[1:].strip()
                    if "+" in example_raw:
                        en_ex, vi_ex = example_raw.split("+", 1)
                        current_examples.append({
                            "text_en": en_ex.strip(),
                            "text_vi": vi_ex.strip(),
                        })
                    else:
                        current_examples.append({
                            "text_en": example_raw.strip(),
                            "text_vi": "",
                        })

            last_entry = flush_entry()
            if last_entry:
                yield last_entry
