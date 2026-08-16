"""
CLOTH Dataset Ingestion Parser.

Parses human-curated Cloze tests authored by English teachers (CLOTH dataset),
extracting grammatically sound question prompts, correct answers, and high-quality distractors.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


class CLOTHParser:
    """Parses CLOTH cloze multiple choice question datasets."""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)

    def parse_drills(self, max_drills: Optional[int] = None) -> Iterator[Dict[str, Any]]:
        """
        Streams cloze reflex drills from the dataset file.
        Each yielded item format:
        {
            "drill_type": "cloze",
            "prompt_text": str,  (e.g., "Fill in the blank: He had to _______ his work.")
            "correct_answer": str,
            "distractors_json": str,  (JSON string: ["opt1", "opt2", "opt3"])
            "target_time_ms": int,
        }
        """
        if not self.file_path.exists():
            logger.warning("CLOTH dataset file not found at %s", self.file_path)
            return

        count = 0
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                for item in data:
                    drills = self._extract_drills_from_item(item)
                    for d in drills:
                        yield d
                        count += 1
                        if max_drills and count >= max_drills:
                            return
            elif isinstance(data, dict):
                # Sometimes organized by subsets e.g. {"data": [...]} or {"middle": [...], "high": [...]}
                for subset_name, subset_items in data.items():
                    if isinstance(subset_items, list):
                        for item in subset_items:
                            drills = self._extract_drills_from_item(item)
                            for d in drills:
                                yield d
                                count += 1
                                if max_drills and count >= max_drills:
                                    return
        except Exception as e:
            logger.error("Error reading CLOTH dataset JSON: %s", e)

    def _extract_drills_from_item(self, item: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []

        # Format 1: Direct single cloze drill format
        if "prompt_text" in item and "correct_answer" in item:
            distractors = item.get("distractors") or []
            if isinstance(distractors, list) and len(distractors) >= 3:
                results.append({
                    "drill_type": "cloze",
                    "prompt_text": item["prompt_text"],
                    "correct_answer": item["correct_answer"].strip(),
                    "distractors_json": json.dumps(distractors[:3], ensure_ascii=False),
                    "target_time_ms": item.get("target_time_ms", 2500),
                })
                return results

        # Format 2: Passage with multiple blanks (Standard CLOTH benchmark format)
        article = item.get("article", "")
        options = item.get("options", [])
        answers = item.get("answers", [])

        if not article or not options or not answers:
            return results

        # Split article into sentences or blank segments
        # Blanks in CLOTH are typically denoted by '_' or '_____'
        blank_pattern = re.compile(r"_+")
        blanks = list(blank_pattern.finditer(article))

        if len(blanks) == len(options) == len(answers):
            for i, match in enumerate(blanks):
                opts = options[i]
                ans_letter = answers[i].strip().upper()
                letter_idx = ord(ans_letter) - ord("A") if len(ans_letter) == 1 and "A" <= ans_letter <= "D" else 0

                if 0 <= letter_idx < len(opts):
                    correct_ans = opts[letter_idx]
                    distractors = [opt for j, opt in enumerate(opts) if j != letter_idx][:3]
                    if len(distractors) == 3:
                        # Extract surrounding sentence context
                        start_pos = max(0, match.start() - 60)
                        end_pos = min(len(article), match.end() + 60)
                        snippet = article[start_pos:match.start()].lstrip(".!?, ") + "_______" + article[match.end():end_pos].rstrip(".!?, ")
                        prompt = f"Fill in the blank: {snippet.strip()}"

                        results.append({
                            "drill_type": "cloze",
                            "prompt_text": prompt,
                            "correct_answer": correct_ans.strip(),
                            "distractors_json": json.dumps(distractors, ensure_ascii=False),
                            "target_time_ms": 2500,
                        })

        return results
