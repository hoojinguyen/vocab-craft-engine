"""
Full Hierarchical JSON Dataset Exporter using Orjson.

Exports complete structured dataset including vocabulary words, nested definitions,
relations, thematic topics, linked parallel sentences, phrases, reflex drills,
and dialogue trees.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List
import orjson

from src.db.duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class JsonExporter:
    """Exports full nested vocabulary dataset into a structured dataset.json."""

    def export(
        self,
        db_mgr: DuckDBManager,
        target_path: Path,
        word_limit: int | None = None,
    ) -> int:
        target_file = Path(target_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)

        conn = db_mgr.get_connection()

        # Step 1: Query words
        word_query = """
            SELECT id, lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level, source
            FROM words
            ORDER BY CASE WHEN frequency_rank IS NOT NULL THEN frequency_rank ELSE 999999 END ASC, id ASC
        """
        if word_limit:
            word_query += f" LIMIT {word_limit}"

        words_rows = conn.execute(word_query).fetchall()
        if not words_rows:
            logger.warning("No words in staging DB to export to JSON")
            payload = {"metadata": {"version": "2.0", "total_words": 0}, "vocabulary": []}
            target_file.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
            return 0

        word_ids = [r[0] for r in words_rows]
        id_set_str = ", ".join(str(wid) for wid in word_ids)

        # Step 2: Query definitions grouped by word_id
        defs_rows = conn.execute(f"""
            SELECT word_id, definition_en, definition_vi, example, source
            FROM definitions
            WHERE word_id IN ({id_set_str})
        """).fetchall()
        defs_by_word: Dict[int, List[Dict[str, Any]]] = {}
        for wid, def_en, def_vi, ex, src in defs_rows:
            if wid not in defs_by_word:
                defs_by_word[wid] = []
            defs_by_word[wid].append({
                "definition_en": def_en,
                "definition_vi": def_vi,
                "example": ex,
                "source": src,
            })

        # Step 3: Query relations grouped by word_id
        rel_rows = conn.execute(f"""
            SELECT word_id, relation_type, target_text, target_word_id, inverted
            FROM word_relations
            WHERE word_id IN ({id_set_str})
        """).fetchall()
        rels_by_word: Dict[int, List[Dict[str, Any]]] = {}
        for wid, rtype, ttext, twid, inv in rel_rows:
            if wid not in rels_by_word:
                rels_by_word[wid] = []
            rels_by_word[wid].append({
                "relation_type": rtype,
                "target_text": ttext,
                "target_word_id": twid,
                "inverted": bool(inv),
            })

        # Step 4: Query topics grouped by word_id
        topics_rows = conn.execute(f"""
            SELECT word_id, topic, raw_topic
            FROM word_topics
            WHERE word_id IN ({id_set_str})
        """).fetchall()
        topics_by_word: Dict[int, List[str]] = {}
        for wid, topic, raw in topics_rows:
            if wid not in topics_by_word:
                topics_by_word[wid] = []
            topics_by_word[wid].append(topic)

        # Step 5: Query linked sentences grouped by word_id
        sent_links = conn.execute(f"""
            SELECT ws.word_id, s.text_en, s.text_vi, s.cefr_level
            FROM word_sentences ws
            JOIN sentences s ON ws.sentence_id = s.id
            WHERE ws.word_id IN ({id_set_str})
        """).fetchall()
        sents_by_word: Dict[int, List[Dict[str, Any]]] = {}
        for wid, ten, tvi, cefr in sent_links:
            if wid not in sents_by_word:
                sents_by_word[wid] = []
            sents_by_word[wid].append({
                "text_en": ten,
                "text_vi": tvi,
                "cefr_level": cefr,
            })

        # Assemble hierarchical vocabulary list
        vocabulary = []
        for wid, lemma, pos, ipa_uk, ipa_us, freq, cefr, src in words_rows:
            vocabulary.append({
                "id": wid,
                "lemma": lemma,
                "pos": pos,
                "ipa": {
                    "uk": ipa_uk,
                    "us": ipa_us,
                },
                "frequency_rank": freq,
                "cefr_level": cefr,
                "definitions": defs_by_word.get(wid, []),
                "relations": rels_by_word.get(wid, []),
                "topics": topics_by_word.get(wid, []),
                "example_sentences": sents_by_word.get(wid, []),
            })

        # Step 6: Query phrases
        phrase_rows = conn.execute("""
            SELECT id, phrase, phrase_type, pos, cefr_level, definition_en, definition_vi
            FROM phrases
        """).fetchall()
        phrases_list = [
            {
                "id": pid,
                "phrase": ptext,
                "type": ptype,
                "pos": ppos,
                "cefr_level": pcefr,
                "definition_en": pdef_en,
                "definition_vi": pdef_vi,
            }
            for pid, ptext, ptype, ppos, pcefr, pdef_en, pdef_vi in phrase_rows
        ]

        # Step 7: Query reflex drills
        drill_rows = conn.execute("""
            SELECT id, sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms
            FROM reflex_drills
        """).fetchall()
        drills_list = []
        for did, sid, dtype, prompt, ans, dist_json, target_ms in drill_rows:
            distractors = []
            if dist_json:
                try:
                    distractors = json.loads(dist_json)
                except Exception:
                    distractors = []
            drills_list.append({
                "id": did,
                "sentence_id": sid,
                "drill_type": dtype,
                "prompt": prompt,
                "correct_answer": ans,
                "distractors": distractors,
                "target_time_ms": target_ms,
            })

        # Assemble full dataset document
        full_payload = {
            "metadata": {
                "version": "2.0",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_words": len(vocabulary),
                "total_phrases": len(phrases_list),
                "total_reflex_drills": len(drills_list),
            },
            "vocabulary": vocabulary,
            "phrases": phrases_list,
            "reflex_drills": drills_list,
        }

        # Write ultra-fast via orjson
        json_bytes = orjson.dumps(full_payload, option=orjson.OPT_INDENT_2)
        target_file.write_bytes(json_bytes)

        logger.info(
            "Exported %d words and %d phrases to %s (%d bytes)",
            len(vocabulary),
            len(phrases_list),
            target_file,
            len(json_bytes),
        )
        return len(vocabulary)
