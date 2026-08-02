"""
Scenario Tree Builder for English Dataset System Engine.
Constructs branching interactive dialogue trees (dialogue_trees and dialogue_nodes).
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ScenarioBuilder:
    """Builds interactive branching dialogue trees for situational practice."""

    def __init__(self):
        pass

    def create_scenario_tree(self, title: str, topic: str, cefr_level: str = "B1") -> Dict[str, Any]:
        """
        Initializes a scenario tree metadata payload.
        """
        return {
            "title": title,
            "topic": topic,
            "cefr_level": cefr_level,
            "nodes": []
        }

    def add_node(
        self,
        tree_id: int,
        speaker_role: str,
        sentence_id: Optional[int],
        parent_node_id: Optional[int] = None,
        choice_label: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates a single dialogue node in the branching graph.
        """
        return {
            "tree_id": tree_id,
            "parent_node_id": parent_node_id,
            "choice_label": choice_label,
            "speaker_role": speaker_role,  # "A" (Bot/Partner) or "B" (User)
            "sentence_id": sentence_id
        }

    def build_sample_scenarios(self) -> List[Dict[str, Any]]:
        """
        Generates sample branching dialogue scenarios for English learners.
        Each node contains text_en, text_vi, speaker_role, choice_label, and parent_index.
        """
        scenarios = [
            {
                "title": "Ordering Coffee at a Cafe",
                "topic": "Daily Conversation",
                "cefr_level": "A2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Hi! What can I get started for you today?",
                        "text_vi": "Xin chào! Bạn muốn gọi món gì hôm nay?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Order a Hot Latte",
                        "text_en": "I'd like a hot latte, please.",
                        "text_vi": "Cho tôi một ly latte nóng."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Order an Iced Coffee",
                        "text_en": "Just an iced Americano for me, thanks.",
                        "text_vi": "Cho tôi một ly Americano đá, cảm ơn."
                    }
                ]
            },
            {
                "title": "Asking for Directions",
                "topic": "Travel & Directions",
                "cefr_level": "B1",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "text_en": "Excuse me, do you know where the subway station is?",
                        "text_vi": "Xin lỗi, bạn có biết ga tàu điện ngầm ở đâu không?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Give directions",
                        "text_en": "Go straight for two blocks, it's on your left.",
                        "text_vi": "Đi thẳng 2 dãy nhà, nó ở bên tay trái bạn."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Polite decline",
                        "text_en": "Sorry, I'm not from around here.",
                        "text_vi": "Xin lỗi, tôi không phải người ở đây."
                    }
                ]
            }
        ]
        return scenarios
