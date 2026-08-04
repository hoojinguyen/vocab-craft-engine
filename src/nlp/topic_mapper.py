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