"""
Scenario Tree Builder for English Dataset System Engine.
Constructs branching interactive dialogue trees (dialogue_trees and dialogue_nodes).
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

TOPIC_KEYWORDS = {
    "Dining & Cafe": ["coffee", "latte", "order", "menu", "drink", "food", "restaurant", "eat", "table"],
    "Travel & Directions": ["subway", "station", "straight", "left", "right", "street", "bus", "direction", "where"],
    "Hotel & Accommodation": ["hotel", "room", "book", "check-in", "reservation", "key", "stay"],
    "Shopping": ["buy", "price", "cost", "store", "size", "pay", "discount"],
    "Daily Conversation": ["hello", "hi", "morning", "how", "good", "thanks", "welcome"]
}


class ScenarioBuilder:
    """Builds interactive branching dialogue trees for situational practice."""

    def __init__(self):
        pass

    def mine_dialogue_trees(self, conn_or_db, max_trees_per_topic: int = 5) -> List[Dict[str, Any]]:
        """Mine 2-turn branching dialogue trees from raw_sentences corpus."""
        conn = conn_or_db.conn if hasattr(conn_or_db, "conn") else conn_or_db
        sentences = conn.execute("""
            SELECT id, text_en, text_vi, cefr_level
            FROM raw_sentences
            WHERE len(string_split(text_en, ' ')) BETWEEN 2 AND 15
        """).fetchall()

        if not sentences:
            return self.build_sample_scenarios()

        scenarios = []

        for topic_name, keywords in TOPIC_KEYWORDS.items():
            # Find matching question sentences for Speaker A
            a_matches = [
                s for s in sentences
                if "?" in s[1] and any(kw in s[1].lower() for kw in keywords)
            ]
            # Find matching response sentences for Speaker B
            b_matches = [
                s for s in sentences
                if "?" not in s[1] and any(kw in s[1].lower() for kw in keywords)
            ]

            trees_count = 0
            for a_sent in a_matches:
                if trees_count >= max_trees_per_topic:
                    break
                if len(b_matches) < 2:
                    continue

                # Sample 2 distinct responses for Speaker B
                b1, b2 = b_matches[0], b_matches[1]

                scenario = {
                    "title": f"{topic_name} Practice",
                    "topic": topic_name,
                    "cefr_level": max([a_sent[3], b1[3], b2[3]], key=lambda c: {"A1":1,"A2":2,"B1":3,"B2":4,"C1":5,"C2":6}.get(c, 3)),
                    "nodes": [
                        {
                            "node_index": 0,
                            "parent_index": None,
                            "speaker_role": "A",
                            "choice_label": None,
                            "sentence_id": a_sent[0],
                            "text_en": a_sent[1],
                            "text_vi": a_sent[2]
                        },
                        {
                            "node_index": 1,
                            "parent_index": 0,
                            "speaker_role": "B",
                            "choice_label": b1[2][:30] if b1[2] else b1[1][:30],
                            "sentence_id": b1[0],
                            "text_en": b1[1],
                            "text_vi": b1[2]
                        },
                        {
                            "node_index": 2,
                            "parent_index": 0,
                            "speaker_role": "B",
                            "choice_label": b2[2][:30] if b2[2] else b2[1][:30],
                            "sentence_id": b2[0],
                            "text_en": b2[1],
                            "text_vi": b2[2]
                        }
                    ]
                }
                scenarios.append(scenario)
                trees_count += 1

        if not scenarios:
            return self.build_sample_scenarios()

        return scenarios

    def build_sample_scenarios(self) -> List[Dict[str, Any]]:
        """Fallback sample branching dialogue scenarios."""
        return [
            {
                "title": "Ordering Coffee at a Cafe",
                "topic": "Dining & Cafe",
                "cefr_level": "A2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "sentence_id": None,
                        "text_en": "Hi! What can I get started for you today?",
                        "text_vi": "Xin chào! Bạn muốn gọi món gì hôm nay?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Order a Hot Latte",
                        "sentence_id": None,
                        "text_en": "I'd like a hot latte, please.",
                        "text_vi": "Cho tôi một ly latte nóng."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Order an Iced Coffee",
                        "sentence_id": None,
                        "text_en": "Just an iced Americano for me, thanks.",
                        "text_vi": "Cho tôi một ly Americano đá, cảm ơn."
                    }
                ]
            }
        ]
