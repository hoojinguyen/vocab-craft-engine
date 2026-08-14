"""Dialogue Tree Scenario Builder with Multi-Branching Conversations."""

import logging
from typing import Any, Dict, List
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

CURATED_SCENARIOS = [
    {
        "title": "Ordering Coffee at a Cafe",
        "topic": "Food & Drink",
        "cefr_level": "A1",
        "nodes": [
            {
                "local_id": 1,
                "parent_local_id": None,
                "speaker_role": "A",
                "choice_label": None,
                "text": "Hello! Welcome to Cafe Mocha. What can I get for you today?",
            },
            {
                "local_id": 2,
                "parent_local_id": 1,
                "speaker_role": "B",
                "choice_label": "Order an iced latte",
                "text": "I'd like a large iced latte with oat milk, please.",
            },
            {
                "local_id": 3,
                "parent_local_id": 1,
                "speaker_role": "B",
                "choice_label": "Order cappuccino & pastry",
                "text": "Could I have a hot cappuccino and a butter croissant?",
            },
            {
                "local_id": 4,
                "parent_local_id": 2,
                "speaker_role": "A",
                "choice_label": None,
                "text": "Sure thing! Would you like any syrup flavor added?",
            },
            {
                "local_id": 5,
                "parent_local_id": 3,
                "speaker_role": "A",
                "choice_label": None,
                "text": "Certainly! Would you like the croissant warmed up?",
            },
        ],
    },
    {
        "title": "Asking for Directions to the Metro",
        "topic": "Travel & Transportation",
        "cefr_level": "A2",
        "nodes": [
            {
                "local_id": 1,
                "parent_local_id": None,
                "speaker_role": "B",
                "choice_label": "Excuse me, where is the nearest station?",
                "text": "Excuse me, could you tell me how to get to the nearest subway station?",
            },
            {
                "local_id": 2,
                "parent_local_id": 1,
                "speaker_role": "A",
                "choice_label": None,
                "text": "Yes, of course! Walk straight down this street for two blocks, then turn left.",
            },
            {
                "local_id": 3,
                "parent_local_id": 2,
                "speaker_role": "B",
                "choice_label": "Ask about distance",
                "text": "Thank you! Is it within walking distance?",
            },
            {
                "local_id": 4,
                "parent_local_id": 2,
                "speaker_role": "B",
                "choice_label": "Ask about ticket machines",
                "text": "Great! Can I buy transit cards at the station entrance?",
            },
            {
                "local_id": 5,
                "parent_local_id": 3,
                "speaker_role": "A",
                "choice_label": None,
                "text": "Yes, it takes only about five minutes on foot.",
            },
        ],
    },
    {
        "title": "Hotel Check-in and Inquiries",
        "topic": "Travel & Transportation",
        "cefr_level": "B1",
        "nodes": [
            {
                "local_id": 1,
                "parent_local_id": None,
                "speaker_role": "A",
                "choice_label": None,
                "text": "Good evening! Welcome to the Grand Hotel. How may I assist you?",
            },
            {
                "local_id": 2,
                "parent_local_id": 1,
                "speaker_role": "B",
                "choice_label": "Check in under my reservation",
                "text": "Hi, I have a reservation under the name Nguyen for three nights.",
            },
            {
                "local_id": 3,
                "parent_local_id": 2,
                "speaker_role": "A",
                "choice_label": None,
                "text": "I see your booking here. May I have your passport and a credit card for the deposit?",
            },
            {
                "local_id": 4,
                "parent_local_id": 3,
                "speaker_role": "B",
                "choice_label": "Hand over ID and ask about breakfast",
                "text": "Here you go. Could you also let me know what time breakfast is served?",
            },
            {
                "local_id": 5,
                "parent_local_id": 4,
                "speaker_role": "A",
                "choice_label": None,
                "text": "Breakfast is served from 6:30 AM to 10:00 AM in the restaurant on the second floor.",
            },
        ],
    },
    {
        "title": "Job Interview: Self Introduction",
        "topic": "Business & Finance",
        "cefr_level": "B2",
        "nodes": [
            {
                "local_id": 1,
                "parent_local_id": None,
                "speaker_role": "A",
                "choice_label": None,
                "text": "Thank you for coming in today. Could you start by telling us a little about your background?",
            },
            {
                "local_id": 2,
                "parent_local_id": 1,
                "speaker_role": "B",
                "choice_label": "Highlight technical experience",
                "text": "Certainly. Over the past five years, I have specialized in building scalable software systems and leading engineering teams.",
            },
            {
                "local_id": 3,
                "parent_local_id": 1,
                "speaker_role": "B",
                "choice_label": "Highlight project management & leadership",
                "text": "Sure! My background is in product delivery and cross-functional team coordination in fast-paced environments.",
            },
            {
                "local_id": 4,
                "parent_local_id": 2,
                "speaker_role": "A",
                "choice_label": None,
                "text": "Impressive. What was the most challenging technical hurdle you recently resolved?",
            },
            {
                "local_id": 5,
                "parent_local_id": 3,
                "speaker_role": "A",
                "choice_label": None,
                "text": "Great. How do you handle conflicting priorities between stakeholder requirements?",
            },
        ],
    },
    {
        "title": "Scheduling a Doctor's Appointment",
        "topic": "Health & Medicine",
        "cefr_level": "B1",
        "nodes": [
            {
                "local_id": 1,
                "parent_local_id": None,
                "speaker_role": "A",
                "choice_label": None,
                "text": "City Medical Center, how can I help you today?",
            },
            {
                "local_id": 2,
                "parent_local_id": 1,
                "speaker_role": "B",
                "choice_label": "Book a routine health checkup",
                "text": "Hello, I would like to schedule a general health checkup with Dr. Smith.",
            },
            {
                "local_id": 3,
                "parent_local_id": 2,
                "speaker_role": "A",
                "choice_label": None,
                "text": "Dr. Smith has availability this Thursday morning at 9:30 AM or Friday afternoon at 2:00 PM.",
            },
            {
                "local_id": 4,
                "parent_local_id": 3,
                "speaker_role": "B",
                "choice_label": "Choose Thursday morning",
                "text": "Thursday morning at 9:30 AM works perfectly for me.",
            },
            {
                "local_id": 5,
                "parent_local_id": 4,
                "speaker_role": "A",
                "choice_label": None,
                "text": "You are confirmed for Thursday at 9:30 AM. Please arrive 10 minutes early to fill out insurance forms.",
            },
        ],
    },
]


class ScenarioBuilder:
    def build(self, db_mgr: DuckDBManager) -> int:
        conn = db_mgr.get_connection()
        created_trees = 0

        for sc in CURATED_SCENARIOS:
            # 1. Insert tree header
            db_mgr.insert_batch_fast("dialogue_trees", [{
                "title": sc["title"],
                "topic": sc["topic"],
                "cefr_level": sc["cefr_level"],
            }])

            # Retrieve newly inserted tree_id
            tree_row = conn.execute(
                "SELECT id FROM dialogue_trees WHERE title = ?",
                [sc["title"]],
            ).fetchone()
            if not tree_row:
                continue
            tree_id = tree_row[0]

            # 2. Insert nodes and track local_id -> db_node_id mapping
            local_to_db_node_id: Dict[int, int] = {}

            for node in sc["nodes"]:
                parent_db_id = local_to_db_node_id.get(node["parent_local_id"]) if node["parent_local_id"] else None

                db_mgr.insert_batch_fast("dialogue_nodes", [{
                    "tree_id": tree_id,
                    "parent_node_id": parent_db_id,
                    "choice_label": node["choice_label"],
                    "speaker_role": node["speaker_role"],
                }])

                node_row = conn.execute("""
                    SELECT id FROM dialogue_nodes 
                    WHERE tree_id = ? AND speaker_role = ? AND (choice_label = ? OR (choice_label IS NULL AND ? IS NULL))
                    ORDER BY id DESC LIMIT 1
                """, [tree_id, node["speaker_role"], node["choice_label"], node["choice_label"]]).fetchone()

                if node_row:
                    local_to_db_node_id[node["local_id"]] = node_row[0]

            created_trees += 1

        logger.info("Generated %d dialogue scenario trees with branching nodes", created_trees)
        return created_trees
