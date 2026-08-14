"""Phrase and Multi-Word Expression Extractor with Morphological Inflection Matching."""

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4

import pyarrow as pa

from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")


@dataclass(frozen=True)
class PhraseExtractionResult:
    phrases_created: int
    links_created: int
    sentences_processed: int
    resumed: bool


def normalize_phrase_text(text: str) -> str:
    """Return a casefolded, tokenized phrase representation."""
    return " ".join(TOKEN_RE.findall(text.casefold()))


CURATED_MWE_CATALOGUE = [
    # Phrasal Verbs
    (
        "give up",
        "phrasal_verb",
        "To cease making an effort; resign; surrender.",
        "B1",
        ["gave up", "given up", "giving up", "gives up"],
    ),
    (
        "break down",
        "phrasal_verb",
        "To stop functioning; decompose; analyze into components.",
        "B1",
        ["broke down", "broken down", "breaking down", "breaks down"],
    ),
    (
        "take off",
        "phrasal_verb",
        "To depart (of aircraft); remove clothing; suddenly succeed.",
        "A2",
        ["took off", "taken off", "taking off", "takes off"],
    ),
    (
        "look for",
        "phrasal_verb",
        "To search for or seek.",
        "A1",
        ["looked for", "looking for", "looks for"],
    ),
    (
        "carry out",
        "phrasal_verb",
        "To perform or execute a task.",
        "B2",
        ["carried out", "carrying out", "carries out"],
    ),
    (
        "take care of",
        "phrasal_verb",
        "To look after or handle responsibilities for.",
        "A2",
        ["took care of", "taken care of", "taking care of", "takes care of"],
    ),
    (
        "look forward to",
        "phrasal_verb",
        "To anticipate with pleasure.",
        "B1",
        ["looked forward to", "looking forward to", "looks forward to"],
    ),
    (
        "get along with",
        "phrasal_verb",
        "To have a harmonious relationship with someone.",
        "B1",
        [
            "got along with",
            "gotten along with",
            "getting along with",
            "gets along with",
        ],
    ),
    (
        "run out of",
        "phrasal_verb",
        "To have no more of something remaining.",
        "A2",
        ["ran out of", "running out of", "runs out of"],
    ),
    (
        "put off",
        "phrasal_verb",
        "To postpone or delay an action.",
        "B1",
        ["putting off", "puts off"],
    ),
    (
        "turn down",
        "phrasal_verb",
        "To refuse or reject; decrease volume.",
        "B1",
        ["turned down", "turning down", "turns down"],
    ),
    (
        "bring up",
        "phrasal_verb",
        "To raise a child; mention a topic.",
        "B2",
        ["brought up", "bringing up", "brings up"],
    ),
    (
        "call off",
        "phrasal_verb",
        "To cancel an event or activity.",
        "B1",
        ["called off", "calling off", "calls off"],
    ),
    (
        "come across",
        "phrasal_verb",
        "To find or meet unexpectedly.",
        "B1",
        ["came across", "coming across", "comes across"],
    ),
    (
        "figure out",
        "phrasal_verb",
        "To understand or find a solution.",
        "B1",
        ["figured out", "figuring out", "figures out"],
    ),
    (
        "find out",
        "phrasal_verb",
        "To discover information or facts.",
        "A2",
        ["found out", "finding out", "finds out"],
    ),
    (
        "hold on",
        "phrasal_verb",
        "To wait for a short time; grip tightly.",
        "A2",
        ["held on", "holding on", "holds on"],
    ),
    (
        "keep up",
        "phrasal_verb",
        "To maintain the same pace or standard.",
        "B1",
        ["kept up", "keeping up", "keeps up"],
    ),
    (
        "set up",
        "phrasal_verb",
        "To establish, arrange, or assemble.",
        "B1",
        ["setting up", "sets up"],
    ),
    (
        "stand out",
        "phrasal_verb",
        "To be clearly noticeable or superior.",
        "B2",
        ["stood out", "standing out", "stands out"],
    ),
    (
        "work out",
        "phrasal_verb",
        "To exercise; resolve successfully.",
        "A2",
        ["worked out", "working out", "works out"],
    ),
    (
        "pick up",
        "phrasal_verb",
        "To lift from a surface; collect someone.",
        "A1",
        ["picked up", "picking up", "picks up"],
    ),
    (
        "catch up",
        "phrasal_verb",
        "To reach the same level or state as another.",
        "B1",
        ["caught up", "catching up", "catches up"],
    ),
    (
        "hang out",
        "phrasal_verb",
        "To spend leisure time casually.",
        "A2",
        ["hung out", "hanging out", "hangs out"],
    ),
    (
        "make up",
        "phrasal_verb",
        "To invent a story; reconcile after an argument.",
        "B1",
        ["made up", "making up", "makes up"],
    ),
    # Idioms
    (
        "break a leg",
        "idiom",
        "Used to wish performers good luck before a show.",
        "B2",
        [],
    ),
    ("piece of cake", "idiom", "Something very easy to accomplish.", "A2", []),
    (
        "bite the bullet",
        "idiom",
        "To endure a painful or difficult situation bravely.",
        "C1",
        [
            "bit the bullet",
            "bitten the bullet",
            "biting the bullet",
            "bites the bullet",
        ],
    ),
    ("under the weather", "idiom", "Feeling slightly ill or unwell.", "B1", []),
    (
        "spill the beans",
        "idiom",
        "To reveal secret information prematurely.",
        "B2",
        [
            "spilled the beans",
            "spilt the beans",
            "spilling the beans",
            "spills the beans",
        ],
    ),
    (
        "hit the nail on the head",
        "idiom",
        "To describe exactly what is causing a situation or problem.",
        "B2",
        ["hitting the nail on the head", "hits the nail on the head"],
    ),
    (
        "cost an arm and a leg",
        "idiom",
        "To be extremely expensive.",
        "B1",
        [
            "costed an arm and a leg",
            "costing an arm and a leg",
            "costs an arm and a leg",
        ],
    ),
    ("once in a blue moon", "idiom", "Occurring very rarely.", "B1", []),
    (
        "see eye to eye",
        "idiom",
        "To agree fully with someone.",
        "B2",
        ["saw eye to eye", "seen eye to eye", "seeing eye to eye", "sees eye to eye"],
    ),
    (
        "burn the midnight oil",
        "idiom",
        "To study or work late into the night.",
        "B2",
        [
            "burned the midnight oil",
            "burnt the midnight oil",
            "burning the midnight oil",
            "burns the midnight oil",
        ],
    ),
    (
        "call it a day",
        "idiom",
        "To stop working on something for the day.",
        "A2",
        ["called it a day", "calling it a day", "calls it a day"],
    ),
    (
        "the best of both worlds",
        "idiom",
        "A situation in which you can enjoy two different advantages.",
        "B2",
        [],
    ),
    # Collocations
    (
        "make a decision",
        "collocation",
        "To decide or choose between alternatives.",
        "A2",
        ["made a decision", "making a decision", "makes a decision"],
    ),
    (
        "take a shower",
        "collocation",
        "To wash oneself under a shower.",
        "A1",
        ["took a shower", "taken a shower", "taking a shower", "takes a shower"],
    ),
    (
        "do homework",
        "collocation",
        "To complete assigned school tasks.",
        "A1",
        ["did homework", "done homework", "doing homework", "does homework"],
    ),
    (
        "pay attention",
        "collocation",
        "To listen or observe attentively.",
        "A2",
        ["paid attention", "paying attention", "pays attention"],
    ),
    (
        "have a good time",
        "collocation",
        "To enjoy an experience.",
        "A1",
        ["had a good time", "having a good time", "has a good time"],
    ),
    (
        "take a break",
        "collocation",
        "To pause work or activity to rest.",
        "A1",
        ["took a break", "taken a break", "taking a break", "takes a break"],
    ),
    (
        "make an effort",
        "collocation",
        "To try hard to do something.",
        "B1",
        ["made an effort", "making an effort", "makes an effort"],
    ),
    (
        "gain experience",
        "collocation",
        "To acquire knowledge through direct participation.",
        "B1",
        ["gained experience", "gaining experience", "gains experience"],
    ),
    (
        "reach an agreement",
        "collocation",
        "To arrive at a mutual consensus.",
        "B2",
        ["reached an agreement", "reaching an agreement", "reaches an agreement"],
    ),
    # Proverbs
    (
        "better late than never",
        "proverb",
        "It is better to do something late than not do it at all.",
        "A2",
        [],
    ),
    (
        "practice makes perfect",
        "proverb",
        "Repeating an activity leads to proficiency.",
        "A2",
        [],
    ),
    (
        "honesty is the best policy",
        "proverb",
        "Being truthful is always the best choice.",
        "B1",
        [],
    ),
    (
        "actions speak louder than words",
        "proverb",
        "What you do is more significant than what you say.",
        "B1",
        [],
    ),
    (
        "knowledge is power",
        "proverb",
        "Having information and skills gives one influence and capability.",
        "A2",
        [],
    ),
]


class PhraseExtractor:
    def extract(
        self, db_mgr: DuckDBManager, *, batch_size: int = 5000
    ) -> PhraseExtractionResult:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")

        candidate_rows = self._candidate_rows(db_mgr)
        if not candidate_rows:
            logger.info("No phrase candidates available for extraction")
            return PhraseExtractionResult(0, 0, 0, resumed=False)

        phrases_before = db_mgr.count_rows("phrases")
        links_before = db_mgr.count_rows("phrase_sentences")
        sentences_processed = 0
        last_sentence_id = 0
        candidate_relation = f"_phrase_candidates_{uuid4().hex}"

        with db_mgr.lock:
            conn = db_mgr.get_connection()
            conn.register(candidate_relation, pa.Table.from_pylist(candidate_rows))
            try:
                while True:
                    sentence_rows = conn.execute(
                        "SELECT id, text_en FROM sentences WHERE id > ? ORDER BY id LIMIT ?",
                        [last_sentence_id, batch_size],
                    ).fetchall()
                    if not sentence_rows:
                        break

                    sentences_processed += len(sentence_rows)
                    last_sentence_id = sentence_rows[-1][0]
                    ngram_rows = list(self._batch_ngrams(sentence_rows))
                    if not ngram_rows:
                        continue

                    ngram_relation = f"_phrase_ngrams_{uuid4().hex}"
                    conn.register(ngram_relation, pa.Table.from_pylist(ngram_rows))
                    try:
                        self._insert_batch_matches(
                            conn, ngram_relation, candidate_relation
                        )
                    finally:
                        conn.unregister(ngram_relation)
            finally:
                conn.unregister(candidate_relation)

        if not sentences_processed:
            logger.warning("No sentences found in staging DB for phrase extraction")
            return PhraseExtractionResult(0, 0, 0, resumed=False)

        phrases_created = db_mgr.count_rows("phrases") - phrases_before
        links_created = db_mgr.count_rows("phrase_sentences") - links_before
        logger.info(
            "Extracted %d unique phrases and created %d phrase-sentence links",
            phrases_created,
            links_created,
        )
        return PhraseExtractionResult(
            phrases_created=phrases_created,
            links_created=links_created,
            sentences_processed=sentences_processed,
            resumed=False,
        )

    @staticmethod
    def _candidate_rows(db_mgr: DuckDBManager) -> list[dict[str, str]]:
        """Build normalized match surfaces mapped to their canonical phrase."""
        candidates: dict[str, dict[str, str]] = {}

        for (
            phrase,
            phrase_type,
            definition_en,
            cefr_level,
            variants,
        ) in CURATED_MWE_CATALOGUE:
            canonical = normalize_phrase_text(phrase)
            for form in [phrase, *variants]:
                surface = normalize_phrase_text(form)
                if surface:
                    candidates[surface] = {
                        "surface": surface,
                        "phrase": canonical,
                        "phrase_type": phrase_type,
                        "definition_en": definition_en,
                        "cefr_level": cefr_level,
                    }

        for (lemma,) in db_mgr.fetch_all("SELECT DISTINCT lemma FROM words"):
            canonical = normalize_phrase_text(lemma)
            token_count = len(canonical.split())
            if not 2 <= token_count <= 6 or canonical in candidates:
                continue
            candidates[canonical] = {
                "surface": canonical,
                "phrase": canonical,
                "phrase_type": "collocation",
                "definition_en": f"Expression: {canonical}",
                "cefr_level": "B1",
            }

        return list(candidates.values())

    @staticmethod
    def _batch_ngrams(
        sentence_rows: list[tuple[int, str]],
    ) -> Iterator[dict[str, object]]:
        """Yield each contiguous normalized two-to-six-token sentence surface."""
        for sentence_id, text_en in sentence_rows:
            tokens = normalize_phrase_text(text_en or "").split()
            for start in range(len(tokens)):
                for width in range(2, min(6, len(tokens) - start) + 1):
                    yield {
                        "sentence_id": sentence_id,
                        "surface": " ".join(tokens[start : start + width]),
                    }

    @staticmethod
    def _insert_batch_matches(
        conn, ngram_relation: str, candidate_relation: str
    ) -> None:
        """Insert matching phrases and links using DuckDB surface equality joins."""
        matches = (
            f"SELECT DISTINCT c.phrase, c.phrase_type, c.definition_en, c.cefr_level "
            f"FROM {ngram_relation} AS n "
            f"JOIN {candidate_relation} AS c ON n.surface = c.surface"
        )
        conn.execute(
            "INSERT OR IGNORE INTO phrases (phrase, phrase_type, definition_en, cefr_level) "
            + matches
        )
        conn.execute(
            "INSERT OR IGNORE INTO phrase_sentences (phrase_id, sentence_id, rank) "
            f"SELECT DISTINCT p.id, n.sentence_id, 1 "
            f"FROM {ngram_relation} AS n "
            f"JOIN {candidate_relation} AS c ON n.surface = c.surface "
            "JOIN phrases AS p ON p.phrase = c.phrase"
        )
