"""
Topic Mapper for English Dataset System Engine.

Maps raw Kaikki topic keys (e.g. "computing") to a curated,
learner-friendly theme taxonomy loaded from config/theme_map.yaml.
Matching order: exact key match, then longest keyword substring match,
then the "General & Everyday" fallback theme.
"""

from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from config.settings import BASE_DIR

THEME_MAP_PATH = BASE_DIR / "config" / "theme_map.yaml"
GENERAL_THEME = "General & Everyday"


class TopicMapper:
    """Maps raw Kaikki topic keys to curated themes."""

    _exact: Dict[str, str] = {}
    _keywords: List[Tuple[str, str]] = []  # (keyword, theme), longest keyword first

    @classmethod
    def _load(cls) -> None:
        if cls._exact or cls._keywords:
            return
        if THEME_MAP_PATH.exists():
            with open(THEME_MAP_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            cls._exact = {k.strip().lower(): v for k, v in (data.get("exact") or {}).items()}
            kw = []
            for theme, keywords in (data.get("keywords") or {}).items():
                for keyword in keywords:
                    kw.append((keyword.strip().lower(), theme))
            cls._keywords = sorted(kw, key=lambda item: len(item[0]), reverse=True)

    @classmethod
    def map_topic(cls, raw: str) -> str:
        cls._load()
        key = (raw or "").strip().lower()
        if not key:
            return GENERAL_THEME
        theme = cls._exact.get(key)
        if theme:
            return theme
        for keyword, theme in cls._keywords:
            if keyword in key:
                return theme
        return GENERAL_THEME


def retheme_word_topics(conn) -> int:
    """
    One-time cleanup: rewrites word_topics so every row's `topic` column is
    the curated theme for its raw_topic (via map_topic). Rows whose raw and
    mapped themes are identical are kept untouched; duplicates (same word,
    same mapped theme) are collapsed. Returns the number of rows updated.
    """
    conn.execute("CREATE TABLE IF NOT EXISTS word_topics_new "
                 "(word_id INTEGER, topic TEXT, raw_topic TEXT, "
                 "UNIQUE (word_id, topic))")
    conn.execute("DELETE FROM word_topics_new")
    cursor = conn.execute("SELECT word_id, topic, raw_topic FROM word_topics")
    batch = cursor.fetchall()
    changed = 0
    for word_id, topic, raw_topic in batch:
        mapped = TopicMapper.map_topic(raw_topic)
        if mapped == topic:
            conn.execute(
                "INSERT OR IGNORE INTO word_topics_new (word_id, topic, raw_topic) "
                "VALUES (?, ?, ?)",
                (word_id, topic, raw_topic),
            )
        else:
            changed += 1
            conn.execute(
                "INSERT OR IGNORE INTO word_topics_new (word_id, topic, raw_topic) "
                "VALUES (?, ?, ?)",
                (word_id, mapped, raw_topic),
            )
    conn.execute("DROP TABLE word_topics")
    conn.execute("ALTER TABLE word_topics_new RENAME TO word_topics")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_word_topics_unique "
                 "ON word_topics(word_id, topic)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_word_topics_topic ON word_topics(topic)")
    conn.commit()
    return changed
