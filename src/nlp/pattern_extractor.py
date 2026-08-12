import json
import logging
from typing import List, Dict, Any, Union
import spacy
from spacy.tokens import Doc
from spacy.matcher import Matcher, DependencyMatcher

logger = logging.getLogger(__name__)

class GrammarPatternExtractor:
    """Extracts English grammar sentence patterns using SpaCy AST & Dependency Matcher."""

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
        self.pattern_meta: Dict[str, Dict[str, str]] = {
            "it_is_adj_to_v": {
                "cefr": "A2",
                "structure": "It + be + Adj + to + Verb"
            },
            "would_mind_ving": {
                "cefr": "B1",
                "structure": "Would + you + mind + V-ing"
            }
        }
        self._init_patterns()

    def _init_patterns(self):
        # 1. it_is_adj_to_v: It is + Adj + to + Verb (Dependency Matcher)
        p_it_adj_to_v = [
            [
                {"RIGHT_ID": "root", "RIGHT_ATTRS": {"LEMMA": "be"}},
                {"LEFT_ID": "root", "REL_OP": ">", "RIGHT_ID": "it", "RIGHT_ATTRS": {"LOWER": "it"}},
                {"LEFT_ID": "root", "REL_OP": ">", "RIGHT_ID": "adj", "RIGHT_ATTRS": {"POS": "ADJ"}},
                {"LEFT_ID": "root", "REL_OP": ">", "RIGHT_ID": "verb", "RIGHT_ATTRS": {"POS": "VERB"}},
            ]
        ]
        self.dep_matcher.add("it_is_adj_to_v", p_it_adj_to_v)

        # Matcher rules for direct token sequences
        self.matcher.add("it_is_adj_to_v_seq", [
            [{"LOWER": "it"}, {"LEMMA": "be"}, {"POS": "ADJ"}, {"LOWER": "to"}, {"POS": "VERB"}]
        ])
        self.matcher.add("would_mind_ving", [
            [{"LOWER": "would"}, {"LOWER": "you"}, {"LOWER": "mind"}, {"TAG": "VBG"}]
        ])

    def extract_patterns(self, text_or_doc: Union[str, Doc]) -> List[Dict[str, Any]]:
        doc = text_or_doc if isinstance(text_or_doc, Doc) else self.nlp(text_or_doc)
        results = []
        seen = set()

        # 1. Direct Token Matcher
        matches = self.matcher(doc)
        for match_id, start, end in matches:
            pattern_name = self.nlp.vocab.strings[match_id].replace("_seq", "")
            if pattern_name not in seen:
                seen.add(pattern_name)
                matched_span = doc[start:end]
                tokens_info = [{"text": t.text, "pos": t.pos_, "lemma": t.lemma_} for t in matched_span]
                meta = self.pattern_meta.get(pattern_name, {"cefr": "B1", "structure": pattern_name})
                results.append({
                    "pattern_name": pattern_name,
                    "cefr_level": meta["cefr"],
                    "structure_json": json.dumps({
                        "matched_text": matched_span.text,
                        "structure": meta["structure"]
                    }),
                    "matched_tokens_json": json.dumps(tokens_info)
                })

        # 2. Dependency Matcher (requires parsed doc)
        if doc.has_annotation("DEP"):
            dep_matches = self.dep_matcher(doc)
            for match_id, token_ids in dep_matches:
                pattern_name = self.nlp.vocab.strings[match_id].replace("_seq", "")
                if pattern_name not in seen:
                    seen.add(pattern_name)
                    min_idx = min(token_ids)
                    max_idx = max(token_ids)
                    matched_span = doc[min_idx : max_idx + 1]
                    tokens_info = [{"text": t.text, "pos": t.pos_, "lemma": t.lemma_} for t in matched_span]
                    meta = self.pattern_meta.get(pattern_name, {"cefr": "B1", "structure": pattern_name})
                    results.append({
                        "pattern_name": pattern_name,
                        "cefr_level": meta["cefr"],
                        "structure_json": json.dumps({
                            "matched_text": matched_span.text,
                            "structure": meta["structure"]
                        }),
                        "matched_tokens_json": json.dumps(tokens_info)
                    })

        return results
