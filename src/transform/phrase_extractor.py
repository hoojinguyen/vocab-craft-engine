"""Phrase and Multi-Word Expression Extractor."""

import logging
import re
from typing import Dict, List, Set, Tuple
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

CURATED_MWE_CATALOGUE = [
    # Phrasal Verbs
    ("give up", "phrasal_verb", "To cease making an effort; resign; surrender.", "B1"),
    ("break down", "phrasal_verb", "To stop functioning; decompose; analyze into components.", "B1"),
    ("take off", "phrasal_verb", "To depart (of aircraft); remove clothing; suddenly succeed.", "A2"),
    ("look for", "phrasal_verb", "To search for or seek.", "A1"),
    ("carry out", "phrasal_verb", "To perform or execute a task.", "B2"),
    ("take care of", "phrasal_verb", "To look after or handle responsibilities for.", "A2"),
    ("look forward to", "phrasal_verb", "To anticipate with pleasure.", "B1"),
    ("get along with", "phrasal_verb", "To have a harmonious relationship with someone.", "B1"),
    ("run out of", "phrasal_verb", "To have no more of something remaining.", "A2"),
    ("put off", "phrasal_verb", "To postpone or delay an action.", "B1"),
    ("turn down", "phrasal_verb", "To refuse or reject; decrease volume.", "B1"),
    ("bring up", "phrasal_verb", "To raise a child; mention a topic.", "B2"),
    ("call off", "phrasal_verb", "To cancel an event or activity.", "B1"),
    ("come across", "phrasal_verb", "To find or meet unexpectedly.", "B1"),
    ("figure out", "phrasal_verb", "To understand or find a solution.", "B1"),
    ("find out", "phrasal_verb", "To discover information or facts.", "A2"),
    ("hold on", "phrasal_verb", "To wait for a short time; grip tightly.", "A2"),
    ("keep up", "phrasal_verb", "To maintain the same pace or standard.", "B1"),
    ("set up", "phrasal_verb", "To establish, arrange, or assemble.", "B1"),
    ("stand out", "phrasal_verb", "To be clearly noticeable or superior.", "B2"),
    ("work out", "phrasal_verb", "To exercise; resolve successfully.", "A2"),
    ("pick up", "phrasal_verb", "To lift from a surface; collect someone.", "A1"),
    ("catch up", "phrasal_verb", "To reach the same level or state as another.", "B1"),
    ("hang out", "phrasal_verb", "To spend leisure time casually.", "A2"),
    ("make up", "phrasal_verb", "To invent a story; reconcile after an argument.", "B1"),

    # Idioms
    ("break a leg", "idiom", "Used to wish performers good luck before a show.", "B2"),
    ("piece of cake", "idiom", "Something very easy to accomplish.", "A2"),
    ("bite the bullet", "idiom", "To endure a painful or difficult situation bravely.", "C1"),
    ("under the weather", "idiom", "Feeling slightly ill or unwell.", "B1"),
    ("spill the beans", "idiom", "To reveal secret information prematurely.", "B2"),
    ("hit the nail on the head", "idiom", "To describe exactly what is causing a situation or problem.", "B2"),
    ("cost an arm and a leg", "idiom", "To be extremely expensive.", "B1"),
    ("once in a blue moon", "idiom", "Occurring very rarely.", "B1"),
    ("see eye to eye", "idiom", "To agree fully with someone.", "B2"),
    ("burn the midnight oil", "idiom", "To study or work late into the night.", "B2"),
    ("call it a day", "idiom", "To stop working on something for the day.", "A2"),
    ("the best of both worlds", "idiom", "A situation in which you can enjoy two different advantages.", "B2"),

    # Collocations
    ("make a decision", "collocation", "To decide or choose between alternatives.", "A2"),
    ("take a shower", "collocation", "To wash oneself under a shower.", "A1"),
    ("do homework", "collocation", "To complete assigned school tasks.", "A1"),
    ("pay attention", "collocation", "To listen or observe attentively.", "A2"),
    ("have a good time", "collocation", "To enjoy an experience.", "A1"),
    ("take a break", "collocation", "To pause work or activity to rest.", "A1"),
    ("make an effort", "collocation", "To try hard to do something.", "B1"),
    ("gain experience", "collocation", "To acquire knowledge through direct participation.", "B1"),
    ("reach an agreement", "collocation", "To arrive at a mutual consensus.", "B2"),

    # Proverbs
    ("better late than never", "proverb", "It is better to do something late than not do it at all.", "A2"),
    ("practice makes perfect", "proverb", "Repeating an activity leads to proficiency.", "A2"),
    ("honesty is the best policy", "proverb", "Being truthful is always the best choice.", "B1"),
    ("actions speak louder than words", "proverb", "What you do is more significant than what you say.", "B1"),
    ("knowledge is power", "proverb", "Having information and skills gives one influence and capability.", "A2"),
]


class PhraseExtractor:
    def extract(self, db_mgr: DuckDBManager) -> int:
        conn = db_mgr.get_connection()

        # Step 1: Scan sentences from staging DB
        sentences = conn.execute("SELECT id, text_en FROM sentences").fetchall()
        if not sentences:
            logger.warning("No sentences found in staging DB for phrase extraction")
            return 0

        # Step 2: Compile regex patterns for MWEs
        compiled_mwes = []
        for phrase, phrase_type, definition_en, cefr_level in CURATED_MWE_CATALOGUE:
            pattern = re.compile(r"\b" + re.escape(phrase) + r"\b", re.IGNORECASE)
            compiled_mwes.append((phrase, phrase_type, definition_en, cefr_level, pattern))

        # Check multi-word lemmas from words table as well
        multi_words = conn.execute("SELECT DISTINCT lemma FROM words WHERE lemma LIKE '% %'").fetchall()
        for row in multi_words:
            m_lemma = row[0].strip().lower()
            if m_lemma and len(m_lemma.split()) >= 2:
                pattern = re.compile(r"\b" + re.escape(m_lemma) + r"\b", re.IGNORECASE)
                compiled_mwes.append((m_lemma, "collocation", f"Expression: {m_lemma}", "B1", pattern))

        # Step 3: Match phrases across sentences
        matched_phrases_data: Dict[str, Tuple[str, str, str]] = {}
        links_data: List[Tuple[str, int]] = []
        seen_links: Set[Tuple[str, int]] = set()

        for sid, text_en in sentences:
            if not text_en:
                continue

            for phrase, phrase_type, def_en, cefr, pattern in compiled_mwes:
                if pattern.search(text_en):
                    if phrase not in matched_phrases_data:
                        matched_phrases_data[phrase] = (phrase_type, def_en, cefr)

                    link_key = (phrase, sid)
                    if link_key not in seen_links:
                        seen_links.add(link_key)
                        links_data.append(link_key)

        if not matched_phrases_data:
            logger.info("No phrases matched in the current sentence dataset")
            return 0

        # Step 4: Batch insert unique phrases into `phrases`
        phrases_to_insert = [
            {
                "phrase": p,
                "phrase_type": ptype,
                "definition_en": pdef,
                "cefr_level": pcefr,
            }
            for p, (ptype, pdef, pcefr) in matched_phrases_data.items()
        ]
        db_mgr.insert_batch_fast("phrases", phrases_to_insert)

        # Step 5: Query real auto-generated `id`s from `phrases` table
        phrase_db_rows = conn.execute("SELECT phrase, id FROM phrases").fetchall()
        phrase_to_id: Dict[str, int] = {row[0]: row[1] for row in phrase_db_rows}

        # Step 6: Batch insert `phrase_sentences` with valid foreign keys
        phrase_sentences_batch = []
        for phrase, sid in links_data:
            pid = phrase_to_id.get(phrase)
            if pid is not None:
                phrase_sentences_batch.append({
                    "phrase_id": pid,
                    "sentence_id": sid,
                    "rank": 1,
                })

        if phrase_sentences_batch:
            db_mgr.insert_batch_fast("phrase_sentences", phrase_sentences_batch)

        logger.info("Extracted %d unique phrases and created %d phrase-sentence links", len(matched_phrases_data), len(phrase_sentences_batch))
        return len(matched_phrases_data)
