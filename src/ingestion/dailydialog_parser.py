"""
DailyDialog Dataset Ingestion Parser.

Parses multi-turn everyday conversational dialogues into structured dialogue trees
and branching interactive nodes for roleplay and situational learning.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

# DailyDialog topic ID to descriptive category mapping
DAILYDIALOG_TOPICS = {
    1: "General & Everyday",
    2: "School Life",
    3: "Culture & Entertainment",
    4: "Emotions & Personality",
    5: "Food & Drink",
    6: "Home & Family",
    7: "Travel & Transportation",
    8: "Health & Medicine",
    9: "Business & Finance",
    10: "Technology",
}


class DailyDialogParser:
    """Parses DailyDialog dataset files (both text format with __eou__ and JSON formats)."""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)

    def parse_trees(self, max_dialogues: Optional[int] = None) -> Iterator[Dict[str, Any]]:
        """
        Parses dialogue scenarios into structured trees and nodes.
        Each yielded tree format:
        {
            "title": str,
            "topic": str,
            "cefr_level": str,
            "nodes": List[{
                "local_id": int,
                "parent_local_id": Optional[int],
                "speaker_role": str, ('A' or 'B')
                "choice_label": Optional[str],
                "text_en": str,
                "text_vi": Optional[str],
            }]
        }
        """
        if not self.file_path.exists():
            logger.warning("DailyDialog file not found at %s", self.file_path)
            return

        count = 0
        # Check if file is JSON
        if self.file_path.suffix.lower() == ".json":
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            tree = self._format_json_tree(item, count + 1)
                            if tree:
                                yield tree
                                count += 1
                                if max_dialogues and count >= max_dialogues:
                                    return
            except Exception as e:
                logger.error("Error reading DailyDialog JSON: %s", e)

        # Plain text format with __eou__ delimiter
        with open(self.file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line_str = line.strip()
                if not line_str or "__eou__" not in line_str:
                    continue

                utterances = [u.strip() for u in line_str.split("__eou__") if u.strip()]
                if len(utterances) < 2:
                    continue

                tree = self._build_linear_tree(utterances, count + 1)
                if tree:
                    yield tree
                    count += 1
                    if max_dialogues and count >= max_dialogues:
                        break

    def _format_json_tree(self, item: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
        turns = item.get("dialogue") or item.get("utterances") or []
        if isinstance(turns, str):
            turns = [u.strip() for u in turns.split("__eou__") if u.strip()]
        if len(turns) < 2:
            return None

        topic = item.get("topic", "General & Everyday")
        cefr = item.get("cefr_level", "B1")
        title = item.get("title", f"Conversation Scenario #{index}: {topic}")

        nodes = []
        for i, turn in enumerate(turns):
            local_id = i + 1
            parent_local_id = i if i > 0 else None
            role = "A" if i % 2 == 0 else "B"
            choice_label = f"Respond: {turn[:30]}..." if role == "B" else None

            nodes.append({
                "local_id": local_id,
                "parent_local_id": parent_local_id,
                "speaker_role": role,
                "choice_label": choice_label,
                "text_en": turn,
                "text_vi": item.get("dialogue_vi", [None] * len(turns))[i] if "dialogue_vi" in item and len(item["dialogue_vi"]) > i else None,
            })

        return {
            "title": title,
            "topic": topic,
            "cefr_level": cefr,
            "nodes": nodes,
        }

    def _build_linear_tree(self, utterances: List[str], index: int) -> Dict[str, Any]:
        first_turn = utterances[0]
        # Infer a natural title from the first turn
        title_snippet = first_turn[:40].replace("?", "").replace("!", "").strip()
        title = f"Scenario #{index}: {title_snippet}"

        # Estimate CEFR based on average utterance length
        avg_len = sum(len(u.split()) for u in utterances) / len(utterances)
        if avg_len <= 6:
            cefr = "A1"
        elif avg_len <= 10:
            cefr = "A2"
        elif avg_len <= 16:
            cefr = "B1"
        else:
            cefr = "B2"

        nodes = []
        for i, turn in enumerate(utterances):
            local_id = i + 1
            parent_local_id = i if i > 0 else None
            role = "A" if i % 2 == 0 else "B"
            choice_label = f"Reply: {turn[:25]}..." if role == "B" else None

            nodes.append({
                "local_id": local_id,
                "parent_local_id": parent_local_id,
                "speaker_role": role,
                "choice_label": choice_label,
                "text_en": turn,
                "text_vi": None,
            })

        return {
            "title": title,
            "topic": "General & Everyday",
            "cefr_level": cefr,
            "nodes": nodes,
        }
