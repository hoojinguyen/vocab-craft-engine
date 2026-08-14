"""Word Topic Mapper using Curated Theme Taxonomy and Contextual Definitions."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
import yaml

from config.settings import THEME_MAP_PATH
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class TopicMapper:
    def __init__(self, config_path: Path | None = None):
        self.config_path = Path(config_path) if config_path else THEME_MAP_PATH
        self._exact_map: Dict[str, str] = {}
        self._keyword_rules: List[Tuple[str, str, int]] = []
        self._load_taxonomy()

    def _load_taxonomy(self) -> None:
        if not self.config_path.exists():
            logger.warning("Theme map config not found at %s. Using default taxonomy.", self.config_path)
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            # Load exact matches
            exact_data = data.get("exact", {})
            self._exact_map = {k.strip().lower(): v for k, v in exact_data.items()}

            # Load keyword rules sorted by length descending (longest match wins)
            keywords_data = data.get("keywords", {})
            rules = []
            for theme, kw_list in keywords_data.items():
                if isinstance(kw_list, list):
                    for kw in kw_list:
                        kw_str = str(kw).strip().lower()
                        if kw_str:
                            rules.append((kw_str, theme, len(kw_str)))

            # Add domain seed vocabulary mapping
            domain_seeds = {
                "doctor": "Health & Medicine",
                "physician": "Health & Medicine",
                "nurse": "Health & Medicine",
                "hospital": "Health & Medicine",
                "clinic": "Health & Medicine",
                "patient": "Health & Medicine",
                "flight": "Travel & Transportation",
                "airplane": "Travel & Transportation",
                "plane": "Travel & Transportation",
                "pilot": "Travel & Transportation",
                "airport": "Travel & Transportation",
                "train": "Travel & Transportation",
                "ticket": "Travel & Transportation",
                "pizza": "Food & Drink",
                "apple": "Food & Drink",
                "bread": "Food & Drink",
                "rice": "Food & Drink",
                "coffee": "Food & Drink",
                "tea": "Food & Drink",
                "computer": "Technology",
                "laptop": "Technology",
                "database": "Technology",
                "algorithm": "Technology",
            }
            for k, v in domain_seeds.items():
                if k not in self._exact_map:
                    self._exact_map[k] = v

            rules.sort(key=lambda x: x[2], reverse=True)
            self._keyword_rules = rules

        except Exception as e:
            logger.error("Failed to load theme_map.yaml: %s", e)

    def map_word(self, lemma: str, definition: str | None = None) -> str:
        norm_lemma = lemma.strip().lower()
        if norm_lemma in self._exact_map:
            return self._exact_map[norm_lemma]

        for kw, theme, _ in self._keyword_rules:
            if kw in norm_lemma:
                return theme

        if definition:
            norm_def = definition.strip().lower()
            for kw, theme, _ in self._keyword_rules:
                if kw in norm_def:
                    return theme

        return "General & Everyday"

    def map_topics(self, db_mgr: DuckDBManager) -> int:
        # Query words along with their first definition (if any)
        rows = db_mgr.fetch_all("""
            SELECT w.id, w.lemma, MIN(d.definition_en)
            FROM words w
            LEFT JOIN definitions d ON w.id = d.word_id
            GROUP BY w.id, w.lemma
        """)

        if not rows:
            logger.warning("No words found in staging DB for topic mapping")
            return 0

        batch: List[Dict[str, Any]] = []
        seen_pairs: Set[Tuple[int, str]] = set()

        for wid, lemma, def_en in rows:
            if not lemma:
                continue

            topic = self.map_word(lemma, def_en)
            pair = (wid, topic)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                batch.append({
                    "word_id": wid,
                    "topic": topic,
                    "raw_topic": topic,
                })

            if len(batch) >= 10000:
                db_mgr.insert_batch_fast("word_topics", batch)
                batch.clear()

        if batch:
            db_mgr.insert_batch_fast("word_topics", batch)

        total_mapped = db_mgr.count_rows("word_topics")
        logger.info("Mapped %d words to thematic categories", total_mapped)
        return total_mapped
