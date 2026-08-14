"""Core 3000 Frequency & Headword Selector."""

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

CONTRACTION_MAP = {
    "dont": "do", "don": "do", "doesnt": "do", "didnt": "do", "doin": "do",
    "cant": "can", "couldnt": "could", "wouldnt": "would", "shouldnt": "should",
    "wont": "will", "isnt": "be", "arent": "be", "wasnt": "be", "werent": "be",
    "im": "i", "ive": "i", "id": "i", "ill": "i",
    "youre": "you", "youve": "you", "youd": "you", "youll": "you",
    "theyre": "they", "theyve": "they", "theyd": "they", "theyll": "they",
    "hes": "he", "shes": "she", "weve": "we", "well": "will",
    "thats": "that", "theres": "there", "havent": "have", "hasnt": "have",
}

NOISE_POS = {
    "name", "prefix", "suffix", "symbol", "particle", "num",
    "punct", "character", "contraction", "affix", "symbol",
}

CEFR_RANK_THRESHOLDS = [
    ("A1", 500),
    ("A2", 1500),
    ("B1", 3500),
    ("B2", 7000),
    ("C1", 15000),
]


def normalize_freq_word(word: str) -> str:
    """Lowercases, strips punctuation/quotes, expands contractions to lemmas."""
    w = (word or "").strip().lower().strip("'\"`-")
    w = w.replace("'", "")
    return CONTRACTION_MAP.get(w, w)


def rank_to_cefr(rank: Optional[int]) -> str:
    """Maps SUBTLEX frequency rank to CEFR proficiency level."""
    if rank is None or rank <= 0:
        return "C2"
    for level, threshold in CEFR_RANK_THRESHOLDS:
        if rank <= threshold:
            return level
    return "C2"


@dataclass
class SelectedWord:
    id: int
    lemma: str
    pos: str
    frequency_rank: Optional[int]
    cefr_level: str
    in_ngsl: bool
    source: str


class CoreSelector:
    """Selects top frequency headwords, filters noise POS, and assigns CEFR levels."""

    def select_core_words(
        self,
        db_mgr: DuckDBManager,
        limit: int = 3000,
        ngsl_path: Optional[Path] = None,
    ) -> List[SelectedWord]:
        ngsl_words: Set[str] = set()
        if ngsl_path and Path(ngsl_path).exists():
            try:
                with open(ngsl_path, "r", encoding="utf-8-sig") as f:
                    for line in f:
                        parts = line.strip().split(",")
                        if parts and parts[0].strip():
                            ngsl_words.add(parts[0].strip().lower())
            except Exception as e:
                logger.warning("Could not parse NGSL file at %s: %s", ngsl_path, e)

        conn = db_mgr.get_connection()
        query = """
            SELECT id, lemma, pos, frequency_rank, source
            FROM words
            WHERE lemma IS NOT NULL AND length(trim(lemma)) > 0
            ORDER BY 
                CASE WHEN frequency_rank IS NOT NULL THEN frequency_rank ELSE 999999 END ASC,
                id ASC
        """
        rows = conn.execute(query).fetchall()

        selected: List[SelectedWord] = []
        seen_lemmas: Set[str] = set()

        for wid, lemma, pos, freq_rank, source in rows:
            pos_norm = (pos or "").strip().lower()
            if pos_norm in NOISE_POS:
                continue

            clean_lemma = normalize_freq_word(lemma)
            if not clean_lemma or clean_lemma in seen_lemmas:
                continue

            seen_lemmas.add(clean_lemma)
            cefr = rank_to_cefr(freq_rank)
            in_ngsl = clean_lemma in ngsl_words

            selected.append(SelectedWord(
                id=wid,
                lemma=clean_lemma,
                pos=pos_norm,
                frequency_rank=freq_rank,
                cefr_level=cefr,
                in_ngsl=in_ngsl,
                source=source or "kaikki",
            ))

            if len(selected) >= limit:
                break

        logger.info("Selected %d core words (NGSL overlap: %d)", len(selected), sum(1 for w in selected if w.in_ngsl))
        return selected
