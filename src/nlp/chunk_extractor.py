"""
Collocation and Phrase Chunk Extractor for English Dataset System Engine.
Extracts Verb-Noun pairs, Phrasal Verbs, and Noun Chunks via Dependency Parsing.
"""

import logging
from typing import List, Dict, Any, Set
import spacy

logger = logging.getLogger(__name__)


class ChunkExtractor:
    """Extracts collocations and lexical chunks from English sentences."""

    def __init__(self, nlp_instance=None):
        if nlp_instance:
            self.nlp = nlp_instance
        else:
            try:
                self.nlp = spacy.load("en_core_web_sm")
            except Exception:
                self.nlp = spacy.blank("en")

    def extract_collocations_from_doc(self, doc) -> List[Dict[str, str]]:
        """
        Extracts collocations from an existing spaCy Doc object.
        """
        collocations = []

        for token in doc:
            # 1. Verb + Direct Object Noun (e.g. "take a break", "make a decision")
            if token.pos_ == "VERB":
                for child in token.children:
                    if child.dep_ in ("dobj", "obj") and child.pos_ == "NOUN":
                        phrase = f"{token.lemma_} {child.lemma_}"
                        collocations.append({
                            "phrase": phrase.lower(),
                            "pos_pattern": "verb + noun",
                            "raw_text": f"{token.text} {child.text}"
                        })

                    # 2. Verb + Preposition / Particle (e.g. "look forward to", "give up")
                    elif child.dep_ in ("prep", "prt") and child.pos_ in ("ADP", "PART"):
                        phrase = f"{token.lemma_} {child.text}"
                        collocations.append({
                            "phrase": phrase.lower(),
                            "pos_pattern": "phrasal verb",
                            "raw_text": f"{token.text} {child.text}"
                        })

        # 3. Noun Chunks (e.g., "heavy rain", "quick response")
        if hasattr(doc, "noun_chunks"):
            for chunk in doc.noun_chunks:
                words = [t for t in chunk if not t.is_stop and t.is_alpha]
                if len(words) >= 2:
                    phrase = " ".join([t.lemma_.lower() for t in words])
                    collocations.append({
                        "phrase": phrase,
                        "pos_pattern": "noun chunk",
                        "raw_text": chunk.text
                    })

        return collocations

    def extract_collocations(self, text: str) -> List[Dict[str, str]]:
        """
        Extracts collocations such as Verb + Object Noun, Phrasal Verbs, and Noun Chunks.
        """
        doc = self.nlp(text)
        return self.extract_collocations_from_doc(doc)
