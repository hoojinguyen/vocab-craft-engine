"""
Lemmatizer and POS Tagger for English Dataset System Engine.
Batch processes sentences using spaCy to extract lemmas and word-sentence relationships.
"""

import logging
from typing import List, Dict, Any, Tuple, Optional, Set
import spacy

logger = logging.getLogger(__name__)


class Lemmatizer:
    """Lemmatizes texts and extracts POS tags using spaCy."""

    def __init__(self, model_name: str = "en_core_web_sm"):
        self.model_name = model_name
        self.nlp = None
        self._load_spacy()

    def _load_spacy(self):
        try:
            self.nlp = spacy.load(self.model_name, disable=["ner"])
        except Exception:
            logger.warning("spaCy model '%s' not found. Loading basic blank English pipeline.", self.model_name)
            self.nlp = spacy.blank("en")
            if "lemmatizer" not in self.nlp.pipe_names:
                # Add simple rule-based lemmatizer if available
                try:
                    self.nlp.add_pipe("lemmatizer", config={"mode": "rule"})
                    self.nlp.initialize()
                except Exception:
                    pass

    def lemmatize_text(self, text: str) -> List[Dict[str, str]]:
        """
        Processes a single sentence string, returning list of token info.
        """
        doc = self.nlp(text)
        tokens_info = []
        for token in doc:
            if token.is_alpha and not token.is_stop:
                lemma = token.lemma_.lower() if token.lemma_ else token.text.lower()
                tokens_info.append({
                    "text": token.text,
                    "lemma": lemma,
                    "pos": token.pos_.lower() if token.pos_ else "noun"
                })
        return tokens_info

    def process_sentence_batch(self, sentences: List[Dict[str, Any]], batch_size: int = 500) -> Iterator[Tuple[Dict[str, Any], List[str]]]:
        """
        Batch processes sentences via nlp.pipe for high throughput.
        Yields (sentence_dict, list_of_lemmas).
        """
        texts = [s["text_en"] for s in sentences]
        docs = self.nlp.pipe(texts, batch_size=batch_size)

        for sentence_dict, doc in zip(sentences, docs):
            lemmas = set()
            for token in doc:
                if token.is_alpha and not token.is_stop and len(token.text) > 1:
                    lemmas.add(token.lemma_.lower() if token.lemma_ else token.text.lower())
            yield sentence_dict, list(lemmas)
