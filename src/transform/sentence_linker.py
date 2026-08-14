"""Word-Sentence Linker Transform with Morphological & Lemmatized Matching."""

import logging
import re
from typing import Dict, List, Set, Tuple
import config.settings  # registers local nltk data paths
from nltk.corpus import wordnet as wn
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"\b[a-zA-Z]+(?:'[a-zA-Z]+)?\b")


class SentenceLinker:
    def link(self, db_mgr: DuckDBManager, batch_size: int = 5000) -> int:
        conn = db_mgr.get_connection()

        # Step 1: Load all distinct lemmas and their IDs into memory
        words = conn.execute("SELECT id, lemma FROM words").fetchall()
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

        # Helper to find candidate lemmas for a given word token
        def get_matching_word_ids(token: str) -> Set[int]:
            matched_ids: Set[int] = set()
            if token in lemma_to_ids:
                matched_ids.update(lemma_to_ids[token])

            # Try WordNet morphy lemmatization across POS tags
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

        # Step 2: Stream sentences and create links
        cursor = conn.cursor()
        cursor.execute("SELECT id, text_en FROM sentences")

        total_links = 0
        link_batch: List[Dict[str, int]] = []
        seen_pairs: Set[Tuple[int, int]] = set()

        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break

            for sid, text_en in rows:
                if not text_en:
                    continue

                tokens = TOKEN_PATTERN.findall(text_en.lower())
                sentence_word_ids: Set[int] = set()

                for token in tokens:
                    wids = get_matching_word_ids(token)
                    sentence_word_ids.update(wids)

                for wid in sentence_word_ids:
                    pair = (wid, sid)
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        link_batch.append({"word_id": wid, "sentence_id": sid})
                        total_links += 1

            if len(link_batch) >= 10000:
                db_mgr.insert_batch_fast("word_sentences", link_batch)
                link_batch.clear()

        if link_batch:
            db_mgr.insert_batch_fast("word_sentences", link_batch)

        logger.info("Successfully created and saved %d word-sentence links", total_links)
        return total_links
