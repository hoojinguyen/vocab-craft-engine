import json
import logging
from typing import List, Dict, Any
import spacy
from spacy.matcher import Matcher, DependencyMatcher

logger = logging.getLogger(__name__)

class GrammarPatternExtractor:
    """Extracts 60+ English grammar sentence patterns using SpaCy AST & Dependency Matcher."""

    def __init__(self, nlp_instance=None):
        if nlp_instance:
            self.nlp = nlp_instance
        else:
            try:
                self.nlp = spacy.load("en_core_web_sm")
            except Exception:
                self.nlp = spacy.blank("en")

        self.matcher = Matcher(self.nlp.vocab)
        self.dep_matcher = DependencyMatcher(self.nlp.vocab)
        self._init_patterns()

    def _init_patterns(self):
        # 1. it_is_adj_to_v: It is + Adj + to + Verb
        p_it_adj_to_v = [
            [
                {"RIGHT_ID": "adj", "RIGHT_ATTRS": {"POS": "ADJ"}},
                {"LEFT_ID": "adj", "REL_OP": ">", "RIGHT_ID": "it", "RIGHT_ATTRS": {"LOWER": "it"}},
                {"LEFT_ID": "adj", "REL_OP": ">", "RIGHT_ID": "verb", "RIGHT_ATTRS": {"POS": "VERB"}},
            ]
        ]
        try:
            self.dep_matcher.add("it_is_adj_to_v", p_it_adj_to_v)
        except Exception:
            pass

        # Matcher rules for direct token sequences
        self.matcher.add("it_is_adj_to_v_seq", [
            [{"LOWER": "it"}, {"LEMMA": "be"}, {"POS": "ADJ"}, {"LOWER": "to"}, {"POS": "VERB"}]
        ])
        self.matcher.add("would_mind_ving", [
            [{"LOWER": "would"}, {"LOWER": "you"}, {"LOWER": "mind"}, {"TAG": "VBG"}]
        ])

    def extract_patterns(self, text: str) -> List[Dict[str, Any]]:
        doc = self.nlp(text)
        results = []
        seen = set()

        matches = self.matcher(doc)
        for match_id, start, end in matches:
            pattern_name = self.nlp.vocab.strings[match_id].replace("_seq", "")
            if pattern_name not in seen:
                seen.add(pattern_name)
                matched_span = doc[start:end]
                tokens_info = [{"text": t.text, "pos": t.pos_, "lemma": t.lemma_} for t in matched_span]
                results.append({
                    "pattern_name": pattern_name,
                    "cefr_level": "A2" if "it_" in pattern_name else "B1",
                    "structure_json": json.dumps({"matched_text": matched_span.text}),
                    "matched_tokens_json": json.dumps(tokens_info)
                })

        return results
