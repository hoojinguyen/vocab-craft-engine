"""Phrase and Multi-Word Expression Extractor with Morphological Inflection Matching."""

import logging
import re
from typing import Dict, List, Set, Tuple
from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)

CURATED_MWE_CATALOGUE = [
    # Phrasal Verbs
    ("give up", "phrasal_verb", "To cease making an effort; resign; surrender.", "B1", ["gave up", "given up", "giving up", "gives up"]),
    ("break down", "phrasal_verb", "To stop functioning; decompose; analyze into components.", "B1", ["broke down", "broken down", "breaking down", "breaks down"]),
    ("take off", "phrasal_verb", "To depart (of aircraft); remove clothing; suddenly succeed.", "A2", ["took off", "taken off", "taking off", "takes off"]),
    ("look for", "phrasal_verb", "To search for or seek.", "A1", ["looked for", "looking for", "looks for"]),
    ("carry out", "phrasal_verb", "To perform or execute a task.", "B2", ["carried out", "carrying out", "carries out"]),
    ("take care of", "phrasal_verb", "To look after or handle responsibilities for.", "A2", ["took care of", "taken care of", "taking care of", "takes care of"]),
    ("look forward to", "phrasal_verb", "To anticipate with pleasure.", "B1", ["looked forward to", "looking forward to", "looks forward to"]),
    ("get along with", "phrasal_verb", "To have a harmonious relationship with someone.", "B1", ["got along with", "gotten along with", "getting along with", "gets along with"]),
    ("run out of", "phrasal_verb", "To have no more of something remaining.", "A2", ["ran out of", "running out of", "runs out of"]),
    ("put off", "phrasal_verb", "To postpone or delay an action.", "B1", ["putting off", "puts off"]),
    ("turn down", "phrasal_verb", "To refuse or reject; decrease volume.", "B1", ["turned down", "turning down", "turns down"]),
    ("bring up", "phrasal_verb", "To raise a child; mention a topic.", "B2", ["brought up", "bringing up", "brings up"]),
    ("call off", "phrasal_verb", "To cancel an event or activity.", "B1", ["called off", "calling off", "calls off"]),
    ("come across", "phrasal_verb", "To find or meet unexpectedly.", "B1", ["came across", "coming across", "comes across"]),
    ("figure out", "phrasal_verb", "To understand or find a solution.", "B1", ["figured out", "figuring out", "figures out"]),
    ("find out", "phrasal_verb", "To discover information or facts.", "A2", ["found out", "finding out", "finds out"]),
    ("hold on", "phrasal_verb", "To wait for a short time; grip tightly.", "A2", ["held on", "holding on", "holds on"]),
    ("keep up", "phrasal_verb", "To maintain the same pace or standard.", "B1", ["kept up", "keeping up", "keeps up"]),
    ("set up", "phrasal_verb", "To establish, arrange, or assemble.", "B1", ["setting up", "sets up"]),
    ("stand out", "phrasal_verb", "To be clearly noticeable or superior.", "B2", ["stood out", "standing out", "stands out"]),
    ("work out", "phrasal_verb", "To exercise; resolve successfully.", "A2", ["worked out", "working out", "works out"]),
    ("pick up", "phrasal_verb", "To lift from a surface; collect someone.", "A1", ["picked up", "picking up", "picks up"]),
    ("catch up", "phrasal_verb", "To reach the same level or state as another.", "B1", ["caught up", "catching up", "catches up"]),
    ("hang out", "phrasal_verb", "To spend leisure time casually.", "A2", ["hung out", "hanging out", "hangs out"]),
    ("make up", "phrasal_verb", "To invent a story; reconcile after an argument.", "B1", ["made up", "making up", "makes up"]),

    # Idioms
    ("break a leg", "idiom", "Used to wish performers good luck before a show.", "B2", []),
    ("piece of cake", "idiom", "Something very easy to accomplish.", "A2", []),
    ("bite the bullet", "idiom", "To endure a painful or difficult situation bravely.", "C1", ["bit the bullet", "bitten the bullet", "biting the bullet", "bites the bullet"]),
    ("under the weather", "idiom", "Feeling slightly ill or unwell.", "B1", []),
    ("spill the beans", "idiom", "To reveal secret information prematurely.", "B2", ["spilled the beans", "spilt the beans", "spilling the beans", "spills the beans"]),
    ("hit the nail on the head", "idiom", "To describe exactly what is causing a situation or problem.", "B2", ["hitting the nail on the head", "hits the nail on the head"]),
    ("cost an arm and a leg", "idiom", "To be extremely expensive.", "B1", ["costed an arm and a leg", "costing an arm and a leg", "costs an arm and a leg"]),
    ("once in a blue moon", "idiom", "Occurring very rarely.", "B1", []),
    ("see eye to eye", "idiom", "To agree fully with someone.", "B2", ["saw eye to eye", "seen eye to eye", "seeing eye to eye", "sees eye to eye"]),
    ("burn the midnight oil", "idiom", "To study or work late into the night.", "B2", ["burned the midnight oil", "burnt the midnight oil", "burning the midnight oil", "burns the midnight oil"]),
    ("call it a day", "idiom", "To stop working on something for the day.", "A2", ["called it a day", "calling it a day", "calls it a day"]),
    ("the best of both worlds", "idiom", "A situation in which you can enjoy two different advantages.", "B2", []),

    # Collocations
    ("make a decision", "collocation", "To decide or choose between alternatives.", "A2", ["made a decision", "making a decision", "makes a decision"]),
    ("take a shower", "collocation", "To wash oneself under a shower.", "A1", ["took a shower", "taken a shower", "taking a shower", "takes a shower"]),
    ("do homework", "collocation", "To complete assigned school tasks.", "A1", ["did homework", "done homework", "doing homework", "does homework"]),
    ("pay attention", "collocation", "To listen or observe attentively.", "A2", ["paid attention", "paying attention", "pays attention"]),
    ("have a good time", "collocation", "To enjoy an experience.", "A1", ["had a good time", "having a good time", "has a good time"]),
    ("take a break", "collocation", "To pause work or activity to rest.", "A1", ["took a break", "taken a break", "taking a break", "takes a break"]),
    ("make an effort", "collocation", "To try hard to do something.", "B1", ["made an effort", "making an effort", "makes an effort"]),
    ("gain experience", "collocation", "To acquire knowledge through direct participation.", "B1", ["gained experience", "gaining experience", "gains experience"]),
    ("reach an agreement", "collocation", "To arrive at a mutual consensus.", "B2", ["reached an agreement", "reaching an agreement", "reaches an agreement"]),

    # Proverbs
    ("better late than never", "proverb", "It is better to do something late than not do it at all.", "A2", []),
    ("practice makes perfect", "proverb", "Repeating an activity leads to proficiency.", "A2", []),
    ("honesty is the best policy", "proverb", "Being truthful is always the best choice.", "B1", []),
    ("actions speak louder than words", "proverb", "What you do is more significant than what you say.", "B1", []),
    ("knowledge is power", "proverb", "Having information and skills gives one influence and capability.", "A2", []),
]


class PhraseExtractor:
    def extract(self, db_mgr: DuckDBManager) -> int:
        # Step 1: Scan sentences from staging DB
        sentences = db_mgr.fetch_all("SELECT id, text_en FROM sentences")
        if not sentences:
            logger.warning("No sentences found in staging DB for phrase extraction")
            return 0

        # Step 2: Compile regex patterns for MWEs including variants
        compiled_mwes: List[Tuple[str, str, str, str, List[re.Pattern]]] = []
        for phrase, phrase_type, definition_en, cefr_level, variants in CURATED_MWE_CATALOGUE:
            all_forms = [phrase] + variants
            patterns = [re.compile(r"\b" + re.escape(form) + r"\b", re.IGNORECASE) for form in all_forms]
            compiled_mwes.append((phrase, phrase_type, definition_en, cefr_level, patterns))

        # Check multi-word lemmas from words table as well
        multi_words = db_mgr.fetch_all("SELECT DISTINCT lemma FROM words WHERE lemma LIKE '% %'")
        for row in multi_words:
            m_lemma = row[0].strip().lower()
            if m_lemma and len(m_lemma.split()) >= 2:
                pattern = re.compile(r"\b" + re.escape(m_lemma) + r"\b", re.IGNORECASE)
                compiled_mwes.append((m_lemma, "collocation", f"Expression: {m_lemma}", "B1", [pattern]))

        # Step 3: Match phrases across sentences
        matched_phrases_data: Dict[str, Tuple[str, str, str]] = {}
        links_data: List[Tuple[str, int]] = []
        seen_links: Set[Tuple[str, int]] = set()

        for sid, text_en in sentences:
            if not text_en:
                continue

            for phrase, phrase_type, def_en, cefr, patterns in compiled_mwes:
                matched = any(p.search(text_en) for p in patterns)
                if matched:
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
        phrase_db_rows = db_mgr.fetch_all("SELECT phrase, id FROM phrases")
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
