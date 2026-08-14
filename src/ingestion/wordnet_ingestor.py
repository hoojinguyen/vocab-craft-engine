"""WordNet Synset, Definition, and Lexical Relation Ingestor."""

import logging
import threading
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid
import nltk
import pyarrow as pa

import config.settings  # registers local nltk data paths
from nltk.corpus import wordnet as wn
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

POS_MAP = {"n": "noun", "v": "verb", "a": "adj", "r": "adv", "s": "adj"}


class WordNetIngestor:
    def ingest(self, db_mgr: DuckDBManager, limit: int | None = None) -> int:
        synsets = list(wn.all_synsets())
        if limit:
            synsets = synsets[:limit]

        # Step 1: Collect and batch insert all distinct WordNet words
        words_batch: List[Dict[str, Any]] = []
        seen_words: Set[Tuple[str, str]] = set()

        for synset in synsets:
            pos = POS_MAP.get(synset.pos(), "noun")
            for lemma in synset.lemmas():
                lemma_name = lemma.name().replace("_", " ").lower()
                key = (lemma_name, pos)
                if key not in seen_words:
                    seen_words.add(key)
                    words_batch.append({
                        "lemma": lemma_name,
                        "pos": pos,
                        "source": "wordnet",
                    })
                    if len(words_batch) >= 20000:
                        db_mgr.insert_batch_fast("words", words_batch)
                        words_batch.clear()

        if words_batch:
            db_mgr.insert_batch_fast("words", words_batch)
            words_batch.clear()

        # Step 2: Dynamic Word ID Resolution Helper
        lemma_pos_to_id: Dict[Tuple[str, str], int] = {}

        def _resolve_keys(keys: Set[Tuple[str, str]]) -> None:
            missing = [k for k in keys if k not in lemma_pos_to_id or lemma_pos_to_id[k] <= 0]
            if not missing:
                return
            missing_list = [{"lemma": k[0], "pos": k[1]} for k in missing]
            arrow_tbl = pa.Table.from_pylist(missing_list)
            temp_name = f"_tmp_wn_words_{threading.get_ident()}_{uuid.uuid4().hex[:8]}"
            with db_mgr.lock:
                conn = db_mgr.get_connection()
                conn.register(temp_name, arrow_tbl)
                try:
                    resolved = conn.execute(
                        f"SELECT w.lemma, w.pos, w.id FROM words w "
                        f"JOIN {temp_name} m ON w.lemma = m.lemma AND w.pos = m.pos"
                    ).fetchall()
                    for r in resolved:
                        lemma_pos_to_id[(r[0], r[1])] = r[2]
                finally:
                    conn.unregister(temp_name)

        # Step 3: Extract definitions and relations with dynamic ID resolution
        defs_batch: List[Dict[str, Any]] = []
        relations_batch: List[Dict[str, Any]] = []
        seen_relations: Set[Tuple[int, str, str]] = set()
        seen_defs: Set[Tuple[int, str]] = set()

        pending_defs: List[Tuple[Tuple[str, str], str, Optional[str]]] = []
        pending_rels: List[Tuple[Tuple[str, str], str, str, Tuple[str, str]]] = []
        count = 0

        def flush_defs_and_rels() -> None:
            if not pending_defs and not pending_rels:
                return

            keys_to_resolve: Set[Tuple[str, str]] = set()
            for src_key, _, _ in pending_defs:
                keys_to_resolve.add(src_key)
            for src_key, _, _, tgt_key in pending_rels:
                keys_to_resolve.add(src_key)
                keys_to_resolve.add(tgt_key)

            _resolve_keys(keys_to_resolve)

            for src_key, def_text, ex_text in pending_defs:
                word_id = lemma_pos_to_id.get(src_key)
                if word_id is not None and word_id > 0 and def_text:
                    def_key = (word_id, def_text)
                    if def_key not in seen_defs:
                        seen_defs.add(def_key)
                        defs_batch.append({
                            "word_id": word_id,
                            "definition_en": def_text,
                            "example": ex_text,
                            "source": "wordnet",
                        })

            for src_key, rel_type, tgt_text, tgt_key in pending_rels:
                word_id = lemma_pos_to_id.get(src_key)
                if word_id is not None and word_id > 0:
                    rel_key = (word_id, rel_type, tgt_text)
                    if rel_key not in seen_relations:
                        seen_relations.add(rel_key)
                        target_id = lemma_pos_to_id.get(tgt_key)
                        target_word_id = target_id if (target_id is not None and target_id > 0) else None
                        relations_batch.append({
                            "word_id": word_id,
                            "relation_type": rel_type,
                            "target_text": tgt_text,
                            "target_word_id": target_word_id,
                            "source": "wordnet",
                        })

            pending_defs.clear()
            pending_rels.clear()

            if len(defs_batch) >= 10000:
                db_mgr.insert_batch_fast("definitions", defs_batch)
                defs_batch.clear()

            if len(relations_batch) >= 10000:
                db_mgr.insert_batch_fast("word_relations", relations_batch)
                relations_batch.clear()

        for synset in synsets:
            pos = POS_MAP.get(synset.pos(), "noun")
            definition_text = synset.definition()
            examples = synset.examples()
            example_text = examples[0] if examples else None

            synset_lemmas = [lemma.name().replace("_", " ").lower() for lemma in synset.lemmas()]

            for lemma in synset.lemmas():
                lemma_name = lemma.name().replace("_", " ").lower()
                src_key = (lemma_name, pos)
                count += 1

                # Definitions
                if definition_text:
                    pending_defs.append((src_key, definition_text, example_text))

                # Synonyms (other lemmas in same synset)
                for target_lemma in synset_lemmas:
                    if target_lemma != lemma_name:
                        pending_rels.append((src_key, "synonym", target_lemma, (target_lemma, pos)))

                # Antonyms
                for ant in lemma.antonyms():
                    ant_name = ant.name().replace("_", " ").lower()
                    ant_pos = POS_MAP.get(ant.synset().pos(), "noun")
                    pending_rels.append((src_key, "antonym", ant_name, (ant_name, ant_pos)))

                # Hypernyms
                for hyper_synset in synset.hypernyms():
                    hyp_pos = POS_MAP.get(hyper_synset.pos(), "noun")
                    for hyper_lemma in hyper_synset.lemmas():
                        hyp_name = hyper_lemma.name().replace("_", " ").lower()
                        pending_rels.append((src_key, "hypernym", hyp_name, (hyp_name, hyp_pos)))

                # Hyponyms
                for hypo_synset in synset.hyponyms():
                    hypo_pos = POS_MAP.get(hypo_synset.pos(), "noun")
                    for hypo_lemma in hypo_synset.lemmas():
                        hypo_name = hypo_lemma.name().replace("_", " ").lower()
                        pending_rels.append((src_key, "hyponym", hypo_name, (hypo_name, hypo_pos)))

            if len(pending_defs) >= 10000 or len(pending_rels) >= 10000:
                flush_defs_and_rels()

        flush_defs_and_rels()

        if defs_batch:
            db_mgr.insert_batch_fast("definitions", defs_batch)
            defs_batch.clear()

        if relations_batch:
            db_mgr.insert_batch_fast("word_relations", relations_batch)
            relations_batch.clear()

        return count
