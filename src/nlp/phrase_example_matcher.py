"""
Tatoeba Example Sentence Matcher for English Dataset System Engine.
Links multi-word expressions to example sentences with boundary-safe matching
and CEFR-priority ranking (easy sentences first).

Matching tolerates verb inflection (e.g. "give up" matches "gave up",
"spring up" matches "springs up") via an irregular-form map plus suffix-
stemming, because Tatoeba sentences use inflected forms far more often than
dictionary base forms. Hyphens are normalized to spaces so "well-known" and
"well known" match each other. Phrase words must appear in order but may have
up to MAX_INSERTED_WORDS words between them, covering object/particle
insertion in phrasal verbs (e.g. "strings her along" for "string along").
"""

import logging
from typing import Dict, Any, List

from src.nlp.phrase_grader import STOPWORDS

logger = logging.getLogger(__name__)

MAX_EXAMPLES_PER_PHRASE = 5
MAX_INSERTED_WORDS = 2
CEFR_ORDER = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}
PUNCT = ".,!?;:\"'()[]-"

IRREGULAR_BASES = {
    "am": "be", "is": "be", "are": "be", "was": "be", "were": "be",
    "been": "be", "being": "be",
    "has": "have", "had": "have", "having": "have",
    "does": "do", "did": "do", "done": "do", "doing": "do",
    "goes": "go", "went": "go", "gone": "go", "going": "go",
    "says": "say", "said": "say", "saying": "say",
    "sees": "see", "saw": "see", "seen": "see", "seeing": "see",
    "makes": "make", "made": "make", "making": "make",
    "takes": "take", "took": "take", "taken": "take", "taking": "take",
    "gets": "get", "got": "get", "gotten": "get", "getting": "get",
    "gives": "give", "gave": "give", "given": "give", "giving": "give",
    "comes": "come", "came": "come", "coming": "come",
    "knows": "know", "knew": "know", "known": "know", "knowing": "know",
    "thinks": "think", "thought": "think", "thinking": "think",
    "finds": "find", "found": "find", "finding": "find",
    "tells": "tell", "told": "tell", "telling": "tell",
    "runs": "run", "ran": "run", "running": "run",
    "eats": "eat", "ate": "eat", "eaten": "eat", "eating": "eat",
    "drinks": "drink", "drank": "drink", "drunk": "drink", "drinking": "drink",
    "writes": "write", "wrote": "write", "written": "write", "writing": "write",
    "reads": "read", "reading": "read",
    "speaks": "speak", "spoke": "speak", "spoken": "speak", "speaking": "speak",
    "feels": "feel", "felt": "feel", "feeling": "feel",
    "keeps": "keep", "kept": "keep", "keeping": "keep",
    "holds": "hold", "held": "hold", "holding": "hold",
    "stands": "stand", "stood": "stand", "standing": "stand",
    "understands": "understand", "understood": "understand", "understanding": "understand",
    "puts": "put", "putting": "put",
    "cuts": "cut", "cutting": "cut",
    "sets": "set", "setting": "set",
    "sits": "sit", "sat": "sit", "sitting": "sit",
    "breaks": "break", "broke": "break", "broken": "break", "breaking": "break",
    "wears": "wear", "wore": "wear", "worn": "wear", "wearing": "wear",
    "buys": "buy", "bought": "buy", "buying": "buy",
    "sells": "sell", "sold": "sell", "selling": "sell",
    "pays": "pay", "paid": "pay", "paying": "pay",
    "lays": "lay", "laid": "lay", "laying": "lay",
    "lies": "lie", "lain": "lie", "lying": "lie",
    "dies": "die", "died": "die", "dying": "die",
    "flies": "fly", "flew": "fly", "flown": "fly", "flying": "fly",
    "grows": "grow", "grew": "grow", "grown": "grow", "growing": "grow",
    "throws": "throw", "threw": "throw", "thrown": "throw", "throwing": "throw",
    "draws": "draw", "drew": "draw", "drawn": "draw", "drawing": "draw",
    "shows": "show", "showed": "show", "shown": "show", "showing": "show",
    "leaves": "leave", "left": "leave", "leaving": "leave",
    "meets": "meet", "met": "meet", "meeting": "meet",
    "sleeps": "sleep", "slept": "sleep", "sleeping": "sleep",
    "sends": "send", "sent": "send", "sending": "send",
    "spends": "spend", "spent": "spend", "spending": "spend",
    "loses": "lose", "lost": "lose", "losing": "lose",
    "wins": "win", "won": "win", "winning": "win",
    "teaches": "teach", "taught": "teach", "teaching": "teach",
    "catches": "catch", "caught": "catch", "catching": "catch",
    "brings": "bring", "brought": "bring", "bringing": "bring",
    "fights": "fight", "fought": "fight", "fighting": "fight",
    "leads": "lead", "led": "lead", "leading": "lead",
    "builds": "build", "built": "build", "building": "build",
    "begins": "begin", "began": "begin", "begun": "begin", "beginning": "begin",
    "swims": "swim", "swam": "swim", "swum": "swim", "swimming": "swim",
    "sings": "sing", "sang": "sing", "sung": "sing", "singing": "sing",
    "rises": "rise", "rose": "rise", "risen": "rise", "rising": "rise",
    "drives": "drive", "drove": "drive", "driven": "drive", "driving": "drive",
    "rides": "ride", "rode": "ride", "ridden": "ride", "riding": "ride",
    "hits": "hit", "hitting": "hit",
    "lets": "let", "letting": "let",
    "used": "use", "using": "use",
    "lived": "live", "living": "live",
    "loved": "love", "loving": "love",
    "moved": "move", "moving": "move",
    # identity entries: words ending in "ing" where "ing" is part of the root,
    # so the base form stems to itself instead of an over-stripped fragment
    "spring": "spring", "sprang": "spring", "sprung": "spring",
    "string": "string", "strung": "string",
    "ring": "ring", "rang": "ring", "rung": "ring",
    "thing": "thing",
    "bring": "bring",
    "king": "king",
    "sing": "sing",
    "wing": "wing",
    "swing": "swing", "swung": "swing",
    "sting": "sting", "stung": "sting",
    "cling": "cling", "clung": "cling",
    "fling": "fling", "flung": "fling",
    "sling": "sling", "slung": "sling",
    "wring": "wring", "wrung": "wring",
    "morning": "morning",
    "evening": "evening",
    "during": "during",
    "ceiling": "ceiling",
    "nothing": "nothing",
    "something": "something",
    "anything": "anything",
    "everything": "everything",
}

INFLECTION_SUFFIXES = ("ing", "ied", "ed", "ies", "es", "s")


def _stem(word: str) -> str:
    """Reduce a word to a rough base form for inflection-tolerant matching."""
    w = word.lower()
    if w in IRREGULAR_BASES:
        return IRREGULAR_BASES[w]
    for suffix in INFLECTION_SUFFIXES:
        if len(w) > len(suffix) + 2 and w.endswith(suffix):
            base = w[:-len(suffix)]
            if suffix in ("ied", "ies"):
                base += "y"
            if len(base) > 2 and base[-1] == base[-2]:
                base = base[:-1]
            return base
    return w


class PhraseExampleMatcher:
    """Finds example sentences containing a given phrase, ranked by difficulty."""

    def __init__(self, sentences: List[Dict[str, Any]]):
        self.sentences = sentences
        self._word_index: Dict[str, List[Dict[str, Any]]] = {}
        self._build_index()

    def _build_index(self):
        """Index sentences by the base form of each word they contain."""
        for sent in self.sentences:
            text = sent["text_en"].lower().replace("-", " ")
            for word in set(text.split()):
                key = _stem(word.strip(PUNCT))
                if key:
                    self._word_index.setdefault(key, []).append(sent)

    @staticmethod
    def _is_boundary_match(phrase: str, sentence: str) -> bool:
        """True if phrase occurs in sentence not surrounded by alphanumeric chars."""
        start = sentence.find(phrase)
        while start != -1:
            end = start + len(phrase)
            before_ok = start == 0 or not sentence[start - 1].isalnum()
            after_ok = end == len(sentence) or not sentence[end].isalnum()
            if before_ok and after_ok:
                return True
            start = sentence.find(phrase, start + 1)
        return False

    @staticmethod
    def _tokens_match_phrase(phrase_words: List[str], sentence: str) -> bool:
        """
        True if phrase words appear in order in sentence, tolerating inflection,
        hyphens, and up to MAX_INSERTED_WORDS words between phrase words.
        """
        tokens = [
            t for t in (w.strip(PUNCT) for w in sentence.replace("-", " ").split())
            if t
        ]
        if len(phrase_words) > len(tokens):
            return False
        for start, token in enumerate(tokens):
            if token != phrase_words[0] and _stem(token) != _stem(phrase_words[0]):
                continue
            pos = start + 1
            matched = True
            for phrase_word in phrase_words[1:]:
                found = False
                for gap in range(MAX_INSERTED_WORDS + 1):
                    idx = pos + gap
                    if idx >= len(tokens):
                        break
                    if tokens[idx] == phrase_word or _stem(tokens[idx]) == _stem(phrase_word):
                        pos = idx + 1
                        found = True
                        break
                if not found:
                    matched = False
                    break
            if matched:
                return True
        return False

    def match_phrase(self, phrase: str, phrase_id: int) -> List[Dict[str, Any]]:
        """
        Returns up to MAX_EXAMPLES_PER_PHRASE mapping dicts
        {'phrase_id', 'sentence_id', 'rank'} for matching sentences.
        """
        words = [w.strip(PUNCT) for w in phrase.lower().replace("-", " ").split()]
        words = [w for w in words if w]
        key_words = [w for w in words if w not in STOPWORDS] or words
        if not key_words:
            return []

        candidates = self._word_index.get(_stem(key_words[0]), [])
        matches = [
            sent for sent in candidates
            if self._is_boundary_match(phrase.lower(), sent["text_en"].lower())
            or self._tokens_match_phrase(words, sent["text_en"].lower())
        ]
        matches.sort(key=lambda s: CEFR_ORDER.get(s.get("cefr_level"), 2))

        return [
            {"phrase_id": phrase_id, "sentence_id": sent["id"], "rank": i + 1}
            for i, sent in enumerate(matches[:MAX_EXAMPLES_PER_PHRASE])
        ]

    def match_phrases(self, phrases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Matches a list of {'id', 'phrase'} dicts, returning all mappings."""
        results: List[Dict[str, Any]] = []
        for phrase_item in phrases:
            results.extend(
                self.match_phrase(phrase_item["phrase"], phrase_item["id"])
            )
        return results
