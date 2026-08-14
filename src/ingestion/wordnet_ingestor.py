"""WordNet Synset, Definition, and Lexical Relation Ingestor."""

import logging
from typing import Any, Dict, List, Set, Tuple
import nltk

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

        conn = db_mgr.get_connection()

        # Step 1: Collect and insert all distinct WordNet words
        existing_words = conn.execute("SELECT lemma, pos, id FROM words").fetchall()
        lemma_pos_to_id: Dict[Tuple[str, str], int] = {(row[0], row[1]): row[2] for row in existing_words}

        words_to_insert: List[Dict[str, Any]] = []
        for synset in synsets:
            pos = POS_MAP.get(synset.pos(), "noun")
            for lemma in synset.lemmas():
                lemma_name = lemma.name().replace("_", " ").lower()
                key = (lemma_name, pos)
                if key not in lemma_pos_to_id:
                    words_to_insert.append({
                        "lemma": lemma_name,
                        "pos": pos,
                        "source": "wordnet",
                    })
                    # Temporary placeholder so we don't duplicate within batch
                    lemma_pos_to_id[key] = -1

        if words_to_insert:
            db_mgr.insert_batch_fast("words", words_to_insert)

        # Refresh full lemma_pos_to_id mapping
        all_words = conn.execute("SELECT lemma, pos, id FROM words").fetchall()
        lemma_pos_to_id = {(row[0], row[1]): row[2] for row in all_words}

        # Step 2: Extract definitions and relations
        defs_batch: List[Dict[str, Any]] = []
        relations_batch: List[Dict[str, Any]] = []
        seen_relations: Set[Tuple[int, str, str]] = set()
        seen_defs: Set[Tuple[int, str]] = set()
        count = 0

        for synset in synsets:
            pos = POS_MAP.get(synset.pos(), "noun")
            definition_text = synset.definition()
            examples = synset.examples()
            example_text = examples[0] if examples else None

            synset_lemmas = [lemma.name().replace("_", " ").lower() for lemma in synset.lemmas()]

            for lemma in synset.lemmas():
                lemma_name = lemma.name().replace("_", " ").lower()
                word_id = lemma_pos_to_id.get((lemma_name, pos))
                if not word_id or word_id == -1:
                    continue

                count += 1

                # Definitions
                if definition_text:
                    def_key = (word_id, definition_text)
                    if def_key not in seen_defs:
                        seen_defs.add(def_key)
                        defs_batch.append({
                            "word_id": word_id,
                            "definition_en": definition_text,
                            "example": example_text,
                            "source": "wordnet",
                        })

                # Synonyms (other lemmas in same synset)
                for target_lemma in synset_lemmas:
                    if target_lemma != lemma_name:
                        rel_key = (word_id, "synonym", target_lemma)
                        if rel_key not in seen_relations:
                            seen_relations.add(rel_key)
                            target_word_id = lemma_pos_to_id.get((target_lemma, pos))
                            relations_batch.append({
                                "word_id": word_id,
                                "relation_type": "synonym",
                                "target_text": target_lemma,
                                "target_word_id": target_word_id if target_word_id != -1 else None,
                                "source": "wordnet",
                            })

                # Antonyms
                for ant in lemma.antonyms():
                    ant_name = ant.name().replace("_", " ").lower()
                    ant_pos = POS_MAP.get(ant.synset().pos(), "noun")
                    rel_key = (word_id, "antonym", ant_name)
                    if rel_key not in seen_relations:
                        seen_relations.add(rel_key)
                        target_word_id = lemma_pos_to_id.get((ant_name, ant_pos))
                        relations_batch.append({
                            "word_id": word_id,
                            "relation_type": "antonym",
                            "target_text": ant_name,
                            "target_word_id": target_word_id if target_word_id != -1 else None,
                            "source": "wordnet",
                        })

                # Hypernyms
                for hyper_synset in synset.hypernyms():
                    hyp_pos = POS_MAP.get(hyper_synset.pos(), "noun")
                    for hyper_lemma in hyper_synset.lemmas():
                        hyp_name = hyper_lemma.name().replace("_", " ").lower()
                        rel_key = (word_id, "hypernym", hyp_name)
                        if rel_key not in seen_relations:
                            seen_relations.add(rel_key)
                            target_word_id = lemma_pos_to_id.get((hyp_name, hyp_pos))
                            relations_batch.append({
                                "word_id": word_id,
                                "relation_type": "hypernym",
                                "target_text": hyp_name,
                                "target_word_id": target_word_id if target_word_id != -1 else None,
                                "source": "wordnet",
                            })

                # Hyponyms
                for hypo_synset in synset.hyponyms():
                    hypo_pos = POS_MAP.get(hypo_synset.pos(), "noun")
                    for hypo_lemma in hypo_synset.lemmas():
                        hypo_name = hypo_lemma.name().replace("_", " ").lower()
                        rel_key = (word_id, "hyponym", hypo_name)
                        if rel_key not in seen_relations:
                            seen_relations.add(rel_key)
                            target_word_id = lemma_pos_to_id.get((hypo_name, hypo_pos))
                            relations_batch.append({
                                "word_id": word_id,
                                "relation_type": "hyponym",
                                "target_text": hypo_name,
                                "target_word_id": target_word_id if target_word_id != -1 else None,
                                "source": "wordnet",
                            })

            if len(defs_batch) >= 5000:
                db_mgr.insert_batch_fast("definitions", defs_batch)
                defs_batch.clear()

            if len(relations_batch) >= 5000:
                db_mgr.insert_batch_fast("word_relations", relations_batch)
                relations_batch.clear()

        if defs_batch:
            db_mgr.insert_batch_fast("definitions", defs_batch)
        if relations_batch:
            db_mgr.insert_batch_fast("word_relations", relations_batch)

        return count
