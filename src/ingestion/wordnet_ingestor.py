"""WordNet Synset and Lexical Relation Ingestor."""

import logging
from typing import Any, Dict, List
import nltk

try:
    nltk.data.find("corpora/wordnet.zip")
except LookupError:
    nltk.download("wordnet")

from nltk.corpus import wordnet as wn
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class WordNetIngestor:
    def ingest(self, db_mgr: DuckDBManager, limit: int | None = None) -> int:
        words_batch: List[Dict[str, Any]] = []
        relations_batch: List[Dict[str, Any]] = []
        count = 0

        synsets = list(wn.all_synsets())
        if limit:
            synsets = synsets[:limit]

        pos_map = {"n": "noun", "v": "verb", "a": "adj", "r": "adv", "s": "adj"}

        for synset in synsets:
            pos = pos_map.get(synset.pos(), "noun")
            for lemma in synset.lemmas():
                lemma_name = lemma.name().replace("_", " ").lower()
                words_batch.append({
                    "lemma": lemma_name,
                    "pos": pos,
                    "source": "wordnet",
                })
                count += 1

                # Synonyms
                for syn in synset.lemmas():
                    target = syn.name().replace("_", " ").lower()
                    if target != lemma_name:
                        relations_batch.append({
                            "word_id": 1,
                            "relation_type": "synonym",
                            "target_text": target,
                            "source": "wordnet",
                        })

                # Antonyms
                for ant in lemma.antonyms():
                    target = ant.name().replace("_", " ").lower()
                    relations_batch.append({
                        "word_id": 1,
                        "relation_type": "antonym",
                        "target_text": target,
                        "source": "wordnet",
                    })

            if len(words_batch) >= 2000:
                db_mgr.insert_batch("words", words_batch)
                words_batch.clear()

            if len(relations_batch) >= 2000:
                db_mgr.insert_batch("word_relations", relations_batch)
                relations_batch.clear()

        if words_batch:
            db_mgr.insert_batch("words", words_batch)
        if relations_batch:
            db_mgr.insert_batch("word_relations", relations_batch)

        return count
