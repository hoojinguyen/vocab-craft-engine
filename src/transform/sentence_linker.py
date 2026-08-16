"""
Curated Word-Sentence Linker Transform with Pedagogical Scoring and Capping V3.

Links words to high-quality example sentences:
1. Scores sentences based on length (6-18 words ideal), translation presence, and source authority.
2. Limits each word to the top N (default: 3) highest-quality examples.
3. Assigns ordinal ranks (1, 2, 3) to enable instant mobile UI retrieval of the best examples.
4. Prevents database bloat by strictly capping link density.
"""

import logging
import re
from typing import Dict, List, Optional, Set, Tuple
import config.settings
from nltk.corpus import wordnet as wn
from src.db.duckdb_manager import DuckDBManager
from config.settings import MAX_SENTENCES_PER_WORD

logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"\b[a-zA-Z]+(?:'[a-zA-Z]+)?\b")

SOURCE_WEIGHTS = {
    "tatoeba": 30.0,
    "fvdp": 30.0,
    "envicorpora": 25.0,
    "ted": 20.0,
    "opensubtitles": 5.0,
}


def score_sentence_candidate(
    text_en: str,
    text_vi: Optional[str] = None,
    source: Optional[str] = None,
) -> float:
    """Computes a pedagogical quality score for an example sentence candidate."""
    if not text_en:
        return 0.0

    tokens = text_en.split()
    length = len(tokens)

    # Penalize overly short (< 4 words) or overly long (> 22 words) sentences
    if length < 4 or length > 25:
        base_score = 30.0
    elif 6 <= length <= 16:
        base_score = 100.0 - abs(length - 10) * 2.0
    else:
        base_score = 70.0

    # Vietnamese translation bonus
    if text_vi and text_vi.strip():
        base_score += 25.0

    # Source bonus
    src_key = (source or "").lower()
    for s_name, weight in SOURCE_WEIGHTS.items():
        if s_name in src_key:
            base_score += weight
            break
    else:
        base_score += 10.0

    return base_score


class SentenceLinker:
    """Links vocabulary words to ranked, high-quality parallel example sentences."""

    def __init__(self, max_per_word: int = MAX_SENTENCES_PER_WORD):
        self.max_per_word = max_per_word

    def link(self, db_mgr: DuckDBManager, batch_size: int = 5000) -> int:
        words = db_mgr.fetch_all("SELECT id, lemma FROM words")
        if not words:
            logger.warning("No words found in staging DB to link")
            return 0

        lemma_to_ids: Dict[str, List[int]] = {}
        for wid, lemma in words:
            if not lemma:
                continue
            norm_lemma = lemma.strip().lower()
            if norm_lemma not in lemma_to_ids:
                lemma_to_ids[norm_lemma] = []
            lemma_to_ids[norm_lemma].append(wid)

        logger.info("Loaded %d lemmas for sentence linking", len(lemma_to_ids))

        def get_matching_word_ids(token: str) -> Set[int]:
            matched_ids: Set[int] = set()
            if token in lemma_to_ids:
                matched_ids.update(lemma_to_ids[token])

            # Try WordNet morphy lemmatization
            try:
                for pos_tag in (wn.NOUN, wn.VERB, wn.ADJ, wn.ADV):
                    lemma_wn = wn.morphy(token, pos_tag)
                    if lemma_wn and lemma_wn in lemma_to_ids:
                        matched_ids.update(lemma_to_ids[lemma_wn])
            except Exception:
                pass

            # Common rule-based suffix fallbacks
            if token.endswith("s") and len(token) > 3:
                cand = token[:-1]
                if cand in lemma_to_ids:
                    matched_ids.update(lemma_to_ids[cand])
                if token.endswith("es") and len(token) > 4:
                    cand_es = token[:-2]
                    if cand_es in lemma_to_ids:
                        matched_ids.update(lemma_to_ids[cand_es])
            elif token.endswith("ed") and len(token) > 4:
                cand = token[:-2]
                if cand in lemma_to_ids:
                    matched_ids.update(lemma_to_ids[cand])
                cand_d = token[:-1]
                if cand_d in lemma_to_ids:
                    matched_ids.update(lemma_to_ids[cand_d])
            elif token.endswith("ing") and len(token) > 5:
                cand = token[:-3]
                if cand in lemma_to_ids:
                    matched_ids.update(lemma_to_ids[cand])
                cand_e = token[:-3] + "e"
                if cand_e in lemma_to_ids:
                    matched_ids.update(lemma_to_ids[cand_e])

            return matched_ids

        # Fetch sentences with text_en, text_vi, source for scoring
        sentences = db_mgr.fetch_all("SELECT id, text_en, text_vi, source FROM sentences")
        logger.info("Evaluating %d sentences for linking...", len(sentences))

        # Map each word_id -> List of (sentence_id, score)
        word_candidates: Dict[int, List[Tuple[int, float]]] = {}

        for sid, text_en, text_vi, source in sentences:
            if not text_en:
                continue

            score = score_sentence_candidate(text_en, text_vi, source)
            tokens = TOKEN_PATTERN.findall(text_en.lower())
            sentence_word_ids: Set[int] = set()

            for token in tokens:
                wids = get_matching_word_ids(token)
                sentence_word_ids.update(wids)

            for wid in sentence_word_ids:
                if wid not in word_candidates:
                    word_candidates[wid] = []
                word_candidates[wid].append((sid, score))

        # Clear existing word_sentences table
        conn = db_mgr.get_connection()
        conn.execute("DELETE FROM word_sentences;")

        # Select Top N per word and build link rows
        total_links = 0
        link_batch: List[Dict[str, int]] = []

        for wid, cand_list in word_candidates.items():
            # Sort by score descending, then sentence_id ascending (deterministic)
            sorted_cands = sorted(cand_list, key=lambda x: (-x[1], x[0]))
            # Deduplicate by sentence_id
            seen_sids: Set[int] = set()
            rank = 1
            for sid, _ in sorted_cands:
                if sid not in seen_sids:
                    seen_sids.add(sid)
                    link_batch.append({
                        "word_id": wid,
                        "sentence_id": sid,
                        "rank": rank,
                    })
                    total_links += 1
                    rank += 1
                    if rank > self.max_per_word:
                        break

            if len(link_batch) >= 10000:
                db_mgr.insert_batch_fast("word_sentences", link_batch)
                link_batch.clear()

        if link_batch:
            db_mgr.insert_batch_fast("word_sentences", link_batch)

        logger.info(
            "Successfully created and saved %d ranked word-sentence links across %d words (capped at %d/word)",
            total_links,
            len(word_candidates),
            self.max_per_word,
        )
        return total_links
