"""
Main Execution Pipeline for English Dataset System Engine.
Orchestrates Ingestion, NLP Enrichment, Collocation Extraction, Dialogue Trees, Reflex Drill Generation, and SQLite Export.
Includes smart step-checkpointing / auto-resume capability to prevent re-processing 3.18GB Kaikki dump on re-runs.
"""

import sys
import logging
import json
import time
import argparse
import asyncio
from pathlib import Path

from config.settings import (
    EXPORT_SQLITE_PATH,
    OUTPUT_DIR,
    KAIKKI_JSON_PATH,
    TATOEBA_SENTENCES_PATH,
    TATOEBA_LINKS_PATH,
    SUBTLEX_FREQ_PATH,
    BATCH_SIZE
)
from src.db.staging_db import DatabaseManager
from src.ingestion.kaikki_parser import KaikkiParser
from src.ingestion.tatoeba_parser import TatoebaParser
from src.nlp.cefr_grader import CEFRGrader
from src.nlp.lemmatizer import Lemmatizer
from src.nlp.chunk_extractor import ChunkExtractor
from src.nlp.reflex_builder import ReflexBuilder
from src.nlp.scenario_builder import ScenarioBuilder
from src.nlp.translator import Translator
from src.nlp.vi_validator import VietnameseTextValidator
from src.media.ipa_mapper import IPAMapper
from src.media.audio_generator import AudioGenerator
from src.export.sqlite_exporter import SQLiteExporter
from src.ingestion.phrase_parser import PhraseParser
from src.nlp.phrase_grader import PhraseGrader
from src.nlp.phrase_example_matcher import PhraseExampleMatcher
from src.ingestion.relation_parser import RelationParser

RELATION_CHECKPOINT = 50_000
TOPIC_CHECKPOINT = 1_000
VI_EMPTY_BACKFILL_CHECKPOINT = 0  # skip when no candidates remain
VI_BATCH_SLEEP_SECONDS = 0.1  # gentle pacing between translation batches (rate-limit backoff)
VI_TRANSLATION_BUDGET = 1000  # max MT attempts per run; re-running resumes the backfill

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


def parse_arguments():
    parser = argparse.ArgumentParser(description="English Dataset System Engine Pipeline Runner")
    parser.add_argument("--force-reset", action="store_true", help="Force complete database reset and re-ingest everything from scratch.")
    parser.add_argument("--skip-dict", action="store_true", help="Skip Step 2 (Kaikki Dictionary Ingestion) if dictionary data is already ingested.")
    parser.add_argument("--vi-budget", type=int, default=VI_TRANSLATION_BUDGET,
                        help="Max MT translation attempts per run for Step 4I backfill (re-run resumes).")
    parser.add_argument("--build-core-pack", action="store_true",
                        help="Build the curated Core 3000 word pack (core_3000.db + report).")
    return parser.parse_args()


def run_phrase_step(db_manager, args) -> dict:
    """
    Step 4G: Ingest multi-word expressions (idioms, phrasal verbs, proverbs)
    from the Kaikki dump, grade CEFR, link Tatoeba examples, generate audio.
    Checkpoint: skips only when > 500 phrases exist AND all have complete audio.
    """
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT count(*) FROM phrases;")
    existing_phrases = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM phrases WHERE audio_std IS NULL OR audio_fast IS NULL;")
    missing_audio = cursor.fetchone()[0]

    if existing_phrases > 500 and missing_audio == 0 and not args.force_reset:
        logger.info("[4G] CHECKPOINT DETECTED: %s phrases with complete audio already exist. Skipping.", f"{existing_phrases:,}")
        return {"phrases": existing_phrases, "links": 0}

    logger.info("   [4G] Ingesting Multi-Word Expressions (Idioms, Phrasal Verbs, Proverbs)...")
    phrase_parser = PhraseParser(KAIKKI_JSON_PATH)
    grader = PhraseGrader(CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH))
    translator = Translator()

    phrases_batch = []
    phrase_count = 0
    for item in phrase_parser.parse_phrases():
        graded = grader.grade_phrase(item["phrase"])
        phrases_batch.append({
            "phrase": item["phrase"],
            "phrase_type": item["phrase_type"],
            "pos": item["pos"],
            "cefr_level": graded["cefr_level"],
            "difficulty_score": graded["difficulty_score"],
            "definition_en": item["definition_en"],
            "definition_vi": item.get("definition_vi") or translator.translate_text(item["phrase"]),
            "ipa": item.get("ipa"),
            "audio_std": None,
            "audio_fast": None,
            "audio_status": "ok"
        })

        if len(phrases_batch) >= 1000:
            db_manager.insert_phrases_batch(phrases_batch)
            phrase_count += len(phrases_batch)
            phrases_batch = []
            logger.info("   -> Staged %s phrases...", f"{phrase_count:,}")

    if phrases_batch:
        db_manager.insert_phrases_batch(phrases_batch)
        phrase_count += len(phrases_batch)
    logger.info("   [4G] Stored %s multi-word expressions.", f"{phrase_count:,}")

    # Link example sentences from Tatoeba
    cursor.execute("SELECT id, text_en, cefr_level FROM sentences;")
    sentence_pool = [
        {"id": r[0], "text_en": r[1], "cefr_level": r[2]}
        for r in cursor.fetchall()
    ]
    matcher = PhraseExampleMatcher(sentence_pool)

    cursor.execute("SELECT id, phrase FROM phrases;")
    stored_phrases = [{"id": r[0], "phrase": r[1]} for r in cursor.fetchall()]
    link_batch = matcher.match_phrases(stored_phrases)
    for i in range(0, len(link_batch), 5000):
        db_manager.insert_phrase_sentences_batch(link_batch[i:i + 5000])
    logger.info("   [4G] Linked %s example sentences to phrases.", f"{len(link_batch):,}")

    # Generate TTS audio for all phrases (batched, one commit per chunk)
    async def generate_phrase_audio():
        audio_gen = AudioGenerator()
        for i in range(0, len(stored_phrases), 10):
            chunk = stored_phrases[i:i + 10]
            results = await asyncio.gather(
                *[audio_gen.generate_dual_speed_phrase(item["id"], item["phrase"]) for item in chunk]
            )
            updates = []
            for item, res in zip(chunk, results):
                status = "ok" if res["standard_path"] and res["fast_path"] else "failed"
                updates.append((
                    str(res["standard_path"]) if res["standard_path"] else None,
                    str(res["fast_path"]) if res["fast_path"] else None,
                    status,
                    item["id"]
                ))
            cursor.executemany(
                "UPDATE phrases SET audio_std = ?, audio_fast = ?, audio_status = ? WHERE id = ?;",
                updates
            )
            conn.commit()

    try:
        asyncio.run(generate_phrase_audio())
        logger.info("   [4G] Generated phrase audio files.")
    except Exception as e:
        logger.warning("   [4G] Phrase audio generation warning: %s", e)

    return {"phrases": phrase_count, "links": len(link_batch)}


def run_relations_step(db_manager, args) -> dict:
    """
    Step 4H: Ingest lexical relations (synonyms, antonyms, hypernyms,
    hyponyms) and topics from the Kaikki dump for single-word entries.
    Checkpoint: skips when > RELATION_CHECKPOINT relations AND
    > TOPIC_CHECKPOINT topic rows exist AND at least one inverted
    (inverse-pass) link exists.
    """
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT count(*) FROM word_relations;")
    existing_relations = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM word_topics;")
    existing_topics = cursor.fetchone()[0]
    cursor.execute("SELECT count(*) FROM word_relations WHERE inverted = 1;")
    existing_inverse = cursor.fetchone()[0]

    if (existing_relations > RELATION_CHECKPOINT and existing_topics > TOPIC_CHECKPOINT
            and existing_inverse > 0 and not args.force_reset):
        logger.info("[4H] CHECKPOINT DETECTED: %s relations, %s inverse links, %s topics already exist. Skipping.", f"{existing_relations:,}", f"{existing_inverse:,}", f"{existing_topics:,}")
        return {"relations": existing_relations, "links": 0, "topics": existing_topics}

    logger.info("   [4H] Building Lexical Relations & Topics (Synonyms, Antonyms, Hypernyms, Hyponyms, Topics)...")
    relation_parser = RelationParser(KAIKKI_JSON_PATH)

    # Lemma -> id map so relation targets can be linked back to the words table
    cursor.execute("SELECT id, lemma FROM words;")
    lemma_map = {lemma: word_id for word_id, lemma in cursor.fetchall()}
    if not lemma_map:
        logger.warning("   [4H] words table is empty — no relations or topics will be linked. Run Step 2 first.")

    relations_batch = []
    topics_batch = []
    relation_count = 0
    topics_count = 0

    for item in relation_parser.parse_entries():
        word_id = lemma_map.get(item["word"])
        if word_id is None:
            continue
        for rel in item["relations"]:
            relations_batch.append({
                "word_id": word_id,
                "relation_type": rel["relation_type"],
                "target_text": rel["target"],
                "target_word_id": lemma_map.get(rel["target"]),
                "inverted": 0,
                "source": rel["source"]
            })
            if len(relations_batch) >= 1000:
                db_manager.insert_word_relations_batch(relations_batch)
                relation_count += len(relations_batch)
                relations_batch = []
                logger.info("   -> Staged %s relations...", f"{relation_count:,}")
        for top in item["topics"]:
            topics_batch.append({"word_id": word_id, "topic": top["topic"], "raw_topic": top["raw_topic"]})
            if len(topics_batch) >= 1000:
                db_manager.insert_word_topics_batch(topics_batch)
                topics_count += len(topics_batch)
                topics_batch = []

    if relations_batch:
        db_manager.insert_word_relations_batch(relations_batch)
        relation_count += len(relations_batch)
    if topics_batch:
        db_manager.insert_word_topics_batch(topics_batch)
        topics_count += len(topics_batch)
    logger.info("   [4H] Stored %s relations and %s topic assignments.", f"{relation_count:,}", f"{topics_count:,}")

    # Inverse pass: each natural hypernym (A -> B) generates hyponym (B -> A), inverted=1
    cursor.execute("""
        SELECT wr.word_id, w.lemma, wr.target_word_id, wr.source
        FROM word_relations wr
        JOIN words w ON w.id = wr.word_id
        WHERE wr.relation_type = 'hypernym' AND wr.inverted = 0 AND wr.target_word_id IS NOT NULL;
    """)
    natural_hypernyms = cursor.fetchall()

    inverse_batch = []
    link_count = 0
    for word_id, lemma, target_word_id, source in natural_hypernyms:
        inverse_batch.append({
            "word_id": target_word_id,
            "relation_type": "hyponym",
            "target_text": lemma,
            "target_word_id": word_id,
            "inverted": 1,
            "source": source
        })
        if len(inverse_batch) >= 5000:
            db_manager.insert_word_relations_batch(inverse_batch)
            link_count += len(inverse_batch)
            inverse_batch = []
    if inverse_batch:
        db_manager.insert_word_relations_batch(inverse_batch)
        link_count += len(inverse_batch)
    logger.info("   [4H] Generated %s inverse hyponym links.", f"{link_count:,}")

    return {"relations": relation_count, "links": link_count, "topics": topics_count}


def run_vietnamese_step(db_manager, args) -> dict:
    """
    Step 4I: Vietnamese translation quality & backfill.
    Cleans English passthrough rows, then backfills missing Vietnamese
    translations (definitions, collocations, phrases) via Translator,
    priority-ordered (graded words first). Only translations that pass
    Vietnamese validation are written. MT calls are capped at args.vi_budget
    per run (default VI_TRANSLATION_BUDGET); re-running resumes the backfill.
    Checkpoint: skips when no candidates remain NULL.
    """
    conn = db_manager.get_connection()
    cursor = conn.cursor()

    # One-time cleanup: English passthrough -> NULL
    cursor.execute("UPDATE definitions SET definition_vi = NULL WHERE definition_vi = definition_en;")
    cursor.execute("UPDATE phrases SET definition_vi = NULL WHERE definition_vi = definition_en;")
    cursor.execute("UPDATE collocations SET meaning_vi = NULL WHERE meaning_vi = phrase;")
    conn.commit()

    # Candidates: missing Vietnamese, graded words first
    cursor.execute("""
        SELECT d.id, d.definition_en FROM definitions d
        JOIN words w ON w.id = d.word_id
        WHERE d.definition_vi IS NULL OR d.definition_vi = ''
        ORDER BY (w.cefr_level IS NULL), d.id;
    """)
    priority_definitions = cursor.fetchall()
    cursor.execute("SELECT id, phrase FROM collocations WHERE meaning_vi IS NULL OR meaning_vi = '';")
    priority_collocations = cursor.fetchall()
    cursor.execute("SELECT id, definition_en FROM phrases WHERE definition_vi IS NULL OR definition_vi = '';")
    priority_phrases = cursor.fetchall()

    remaining = len(priority_definitions) + len(priority_collocations) + len(priority_phrases)
    if remaining == VI_EMPTY_BACKFILL_CHECKPOINT and not args.force_reset:
        logger.info("[4I] CHECKPOINT DETECTED: no missing Vietnamese translations remain. Skipping.")
        return {"definitions": 0, "collocations": 0, "phrases": 0}

    logger.info("   [4I] Backfilling Vietnamese translations (%s definitions, %s collocations, %s phrases)...",
                f"{len(priority_definitions):,}", f"{len(priority_collocations):,}", f"{len(priority_phrases):,}")

    translator = Translator()
    validator = VietnameseTextValidator()
    translated_defs = 0
    translated_colls = 0
    translated_phrases = 0

    budget = getattr(args, "vi_budget", VI_TRANSLATION_BUDGET)

    # Reserve fixed slices for collocations and phrases so they are never
    # starved by the ~1.4M definitions (all words are graded, so the plain
    # graded-first order would never reach them). Remainder goes to definitions.
    colloc_budget = 0
    phrase_budget = 0
    defs_budget = 0
    if budget >= 3:
        small_table_slice = max(1, budget // 10)
        colloc_budget = min(len(priority_collocations), small_table_slice)
        phrase_budget = min(len(priority_phrases), small_table_slice)
        defs_budget = max(0, budget - colloc_budget - phrase_budget)
    elif budget > 0:
        colloc_budget = min(len(priority_collocations), budget)

    def _backfill(rows, table, id_col, target_col, remaining_budget):
        """Translate up to remaining_budget rows and UPDATE; returns (updated, budget_left)."""
        updated = 0
        batches_done = 0
        for batch_start in range(0, len(rows), 1000):
            if remaining_budget <= 0:
                break
            batch = rows[batch_start:batch_start + 1000]
            updates = []
            for row_id, text in batch:
                if remaining_budget <= 0:
                    break
                remaining_budget -= 1
                vi = translator.translate_text(text)
                if vi and validator.is_vietnamese(vi):
                    updates.append((vi, row_id))
            if updates:
                # table/id_col/target_col are hardcoded literals at call sites; values are parameterized
                cursor.executemany(
                    f"UPDATE {table} SET {target_col} = ? WHERE {id_col} = ?;",
                    updates
                )
                conn.commit()
                updated += len(updates)
            batches_done += 1
            if batches_done % 10 == 0:
                logger.info("   -> Translated %s %s so far...", f"{updated:,}", table)
            time.sleep(VI_BATCH_SLEEP_SECONDS)
        return updated, remaining_budget

    translated_defs, _ = _backfill(priority_definitions, "definitions", "id", "definition_vi", defs_budget)
    if hasattr(translator, "save_cache"):
        translator.save_cache()
    translated_colls, _ = _backfill(priority_collocations, "collocations", "id", "meaning_vi", colloc_budget)
    if hasattr(translator, "save_cache"):
        translator.save_cache()
    translated_phrases, _ = _backfill(priority_phrases, "phrases", "id", "definition_vi", phrase_budget)
    if hasattr(translator, "save_cache"):
        translator.save_cache()

    logger.info("   [4I] Translated: %s definitions, %s collocations, %s phrases (rest kept NULL).",
                f"{translated_defs:,}", f"{translated_colls:,}", f"{translated_phrases:,}")

    return {"definitions": translated_defs, "collocations": translated_colls, "phrases": translated_phrases}


def run_core_pack_step(db_manager, args) -> dict:
    """
    Step 6: Build the curated Core 3000 word pack.
    Selects 3,000 most common words (NGSL + Tatoeba gated), enriches each
    word with quality gates, and exports core_3000.db + quality_report.md
    to data/output/core_pack/.
    """
    from config.settings import NGSL_PATH
    from src.export.core_pack_builder import CorePackBuilder

    conn = db_manager.get_connection()

    # Load frequency ranks once (rank 1 = most common)
    grader = CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH)
    freq_dict = dict(grader.freq_dict)

    pack_dir = OUTPUT_DIR / "core_pack"
    builder = CorePackBuilder(source_db_path=EXPORT_SQLITE_PATH, output_dir=pack_dir)
    report = builder.build(freq_dict=freq_dict, ngsl_path=NGSL_PATH, vi_budget=args.vi_budget)

    logger.info("[Step 6/6] Core pack built: %s words, pass rate %.1f%%, %s quarantined, %s themes.",
                f"{report['selected']:,}", report["pass_rate"] * 100,
                report["quarantined"], report["themes_covered"])
    return report


def run_pipeline():
    args = parse_arguments()
    start_time = time.time()
    logger.info("==========================================================")
    logger.info("   STARTING ENGLISH DATASET SYSTEM PIPELINE EXECUTION    ")
    logger.info("==========================================================")

    # Check raw data files
    if not KAIKKI_JSON_PATH.exists() or not TATOEBA_SENTENCES_PATH.exists() or not SUBTLEX_FREQ_PATH.exists():
        logger.info("Raw data files check/download in progress...")
        from scripts.download_raw_data import download_all_raw_data
        download_all_raw_data()

    # Step 1: Initialize Database & Schema
    logger.info("[Step 1/5] Initializing SQLite Database Schema...")
    db_manager = DatabaseManager(db_path=EXPORT_SQLITE_PATH)

    if args.force_reset and EXPORT_SQLITE_PATH.exists():
        logger.info("   -> Force-reset flag active. Wiping existing database tables...")
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        conn.execute("PRAGMA foreign_keys = OFF;")
        tables_to_drop = [
            "word_relations", "word_topics", "word_sentence_map", "reflex_drills", "dialogue_nodes",
            "dialogue_trees", "sentences", "sentence_patterns",
            "collocations", "definitions", "words"
        ]
        for tbl in tables_to_drop:
            cursor.execute(f"DROP TABLE IF EXISTS {tbl};")
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON;")

    db_manager.init_schema()
    logger.info("[Step 1/5] Schema initialized successfully.")

    conn = db_manager.get_connection()
    cursor = conn.cursor()

    # Check existing data counts to support smart auto-resume / checkpointing
    cursor.execute("SELECT count(*) FROM words;")
    existing_words = cursor.fetchone()[0]

    cursor.execute("SELECT count(*) FROM definitions;")
    existing_defs = cursor.fetchone()[0]

    # Initialize CEFR Grader with frequency ranks
    grader = CEFRGrader(subtlex_path=SUBTLEX_FREQ_PATH)

    # Step 2: Ingest Kaikki Dictionary (Smart Auto-Skip if > 10,000 words already exist)
    if (existing_words > 10000 and existing_defs > 10000 and not args.force_reset) or args.skip_dict:
        logger.info("[Step 2/5] CHECKPOINT DETECTED: %s words & %s definitions already exist in database.", f"{existing_words:,}", f"{existing_defs:,}")
        logger.info("[Step 2/5] SKIPPING Step 2 (Saved ~15 minutes!). Use --force-reset to re-ingest.")
    else:
        logger.info("[Step 2/5] Ingesting Kaikki Dictionary (3.18 GB dump)...")
        kaikki_parser = KaikkiParser(KAIKKI_JSON_PATH)
        ipa_mapper = IPAMapper()

        words_batch = []
        definitions_batch = []

        count = 0
        words_count = 0
        definitions_count = 0

        for item in kaikki_parser.parse_stream():
            count += 1
            lemma = item["lemma"]
            pos = item["pos"]
            ipa_uk = item["ipa_uk"]
            ipa_us = item["ipa_us"]

            final_ipa_us = ipa_mapper.get_ipa(lemma, existing_ipa=ipa_us)
            final_ipa_uk = ipa_mapper.get_ipa(lemma, existing_ipa=ipa_uk)

            cefr_lvl, freq_rank = grader.grade_word(lemma)

            words_batch.append({
                "lemma": lemma,
                "pos": pos,
                "ipa_uk": final_ipa_uk,
                "ipa_us": final_ipa_us,
                "frequency_rank": freq_rank,
                "cefr_level": cefr_lvl
            })

            if len(words_batch) >= 5000:
                db_manager.insert_words_batch(words_batch)
                words_count += len(words_batch)
                words_batch = []

            if count % 50000 == 0:
                logger.info("   -> Processed %s dictionary entries (%s words staged)...", f"{count:,}", f"{words_count:,}")

        if words_batch:
            db_manager.insert_words_batch(words_batch)
            words_count += len(words_batch)

        logger.info("[Step 2/5] Completed words ingestion: %s words stored.", f"{words_count:,}")

        # Ingest definitions
        logger.info("   -> Extracting definitions and Vietnamese translations...")
        def_stream_count = 0
        for item in kaikki_parser.parse_stream():
            def_stream_count += 1
            word_id = db_manager.get_word_id_by_lemma(item["lemma"])
            if word_id:
                for def_item in item["definitions"]:
                    definitions_batch.append({
                        "word_id": word_id,
                        "definition_en": def_item["definition_en"],
                        "definition_vi": def_item.get("definition_vi"),
                        "example": def_item.get("example"),
                        "source": def_item["source"]
                    })

                    if len(definitions_batch) >= 5000:
                        db_manager.insert_definitions_batch(definitions_batch)
                        definitions_count += len(definitions_batch)
                        definitions_batch = []

            if def_stream_count % 100000 == 0:
                logger.info("   -> Staged %s definitions...", f"{definitions_count:,}")

        if definitions_batch:
            db_manager.insert_definitions_batch(definitions_batch)
            definitions_count += len(definitions_batch)

        logger.info("[Step 2/5] Completed definitions ingestion: %s definitions stored.", f"{definitions_count:,}")

    # Check sentences count for Step 3 checkpointing
    cursor.execute("SELECT count(*) FROM sentences;")
    existing_sentences = cursor.fetchone()[0]

    # Step 3: Ingest Tatoeba Aligned Sentences (Smart Auto-Skip if > 1,000 sentences already exist)
    if existing_sentences > 1000 and not args.force_reset:
        logger.info("[Step 3/5] CHECKPOINT DETECTED: %s sentence pairs already exist in database.", f"{existing_sentences:,}")
        logger.info("[Step 3/5] SKIPPING Step 3. Use --force-reset to re-ingest.")
    else:
        logger.info("[Step 3/5] Ingesting Tatoeba Parallel Sentences...")
        tatoeba_parser = TatoebaParser(TATOEBA_SENTENCES_PATH, TATOEBA_LINKS_PATH)
        sentences_batch = []
        sent_count = 0

        for pair in tatoeba_parser.parse_aligned_pairs():
            graded = grader.grade_sentence(pair["text_en"])
            sentences_batch.append({
                "text_en": pair["text_en"],
                "text_vi": pair["text_vi"],
                "difficulty_score": graded["difficulty_score"],
                "cefr_level": graded["cefr_level"],
                "audio_path": f"sent_{sent_count + len(sentences_batch)}_std.mp3",
                "source": pair["source"]
            })

            if len(sentences_batch) >= 5000:
                db_manager.insert_sentences_batch(sentences_batch)
                sent_count += len(sentences_batch)
                sentences_batch = []
                logger.info("   -> Staged %s aligned sentence pairs...", f"{sent_count:,}")

        if sentences_batch:
            db_manager.insert_sentences_batch(sentences_batch)
            sent_count += len(sentences_batch)

        logger.info("[Step 3/5] Completed sentence pairs ingestion: %s pairs stored.", f"{sent_count:,}")

    # Step 4: NLP Enrichment & Reflex Drill Generation
    logger.info("[Step 4/5] Running NLP Enrichment across all 9 schema tables...")

    # 4A. Collocation Extraction & Translation
    cursor.execute("SELECT id, text_en FROM sentences;")
    all_sentences = cursor.fetchall()
    cursor.execute("SELECT count(*) FROM collocations;")
    existing_collocs = cursor.fetchone()[0]
    if existing_collocs > 500 and not args.force_reset:
        logger.info("   [4A] CHECKPOINT DETECTED: %s collocations already exist. Skipping re-translation.", f"{existing_collocs:,}")
    else:
        logger.info("   [4A] Extracting & Translating Verb+Noun & Phrasal Verb Collocations...")
        chunk_extractor = ChunkExtractor()
        translator = Translator()

        colloc_batch = []
        seen_phrases = set()
        for s_id, text_en in all_sentences:
            chunks = chunk_extractor.extract_collocations(text_en)
            for chunk in chunks:
                phrase = chunk["phrase"]
                if phrase not in seen_phrases:
                    seen_phrases.add(phrase)
                    c_level, _ = grader.grade_word(phrase.split()[0] if phrase else "the")
                    colloc_batch.append({
                        "phrase": phrase,
                        "meaning_vi": translator.translate_text(phrase),
                        "pos_pattern": chunk["pos_pattern"],
                        "cefr_level": c_level if c_level in ("A1", "A2", "B1", "B2") else "B1"
                    })

                if len(colloc_batch) >= 1000:
                    db_manager.insert_collocations_batch(colloc_batch)
                    colloc_batch = []

        if colloc_batch:
            db_manager.insert_collocations_batch(colloc_batch)

        cursor.execute("SELECT count(*) FROM collocations;")
        colloc_count = cursor.fetchone()[0]
        logger.info("   [4A] Inserted %s collocations with Vietnamese translations.", f"{colloc_count:,}")

    # 4B. Word-Sentence Mapping & Lemmatization
    logger.info("   [4B] Linking Word-Sentence Mappings across all sentences...")
    lemmatizer = Lemmatizer()
    map_batch = []
    for s_id, text_en in all_sentences:
        lemmas = lemmatizer.lemmatize_text(text_en)
        for lem in lemmas:
            word_id = db_manager.get_word_id_by_lemma(lem["lemma"])
            if word_id:
                map_batch.append({"word_id": word_id, "sentence_id": s_id})

            if len(map_batch) >= 5000:
                db_manager.insert_word_sentence_map_batch(map_batch)
                map_batch = []

    if map_batch:
        db_manager.insert_word_sentence_map_batch(map_batch)

    cursor.execute("SELECT count(*) FROM word_sentence_map;")
    map_count = cursor.fetchone()[0]
    logger.info("   [4B] Inserted %s word-sentence links.", f"{map_count:,}")

    # 4C. Sentence Patterns Population
    logger.info("   [4C] Populating Sentence Patterns...")
    patterns = [
        {"pattern_name": "Subject + Verb + Object", "structure_json": json.dumps(["NP", "VP", "NP"]), "example_en": "She drinks hot coffee.", "example_vi": "Cô ấy uống cà phê nóng.", "cefr_level": "A1"},
        {"pattern_name": "Subject + Verb + Prepositional Phrase", "structure_json": json.dumps(["NP", "VP", "PP"]), "example_en": "They run in the park.", "example_vi": "Họ chạy trong công viên.", "cefr_level": "A2"},
        {"pattern_name": "Subject + Auxiliary + Verb + Object", "structure_json": json.dumps(["NP", "AUX", "VP", "NP"]), "example_en": "I can learn English.", "example_vi": "Tôi có thể học tiếng Anh.", "cefr_level": "B1"}
    ]
    patterns_count = db_manager.insert_sentence_patterns_batch(patterns)
    logger.info("   [4C] Populated %d sentence patterns.", patterns_count)

    # 4D. Interactive Dialogue Scenarios
    logger.info("   [4D] Building Interactive Dialogue Trees with Dynamic Sentence Linking...")
    scenario_builder = ScenarioBuilder()
    scenarios = scenario_builder.build_sample_scenarios()

    for sc in scenarios:
        cursor.execute("""
            INSERT INTO dialogue_trees (title, topic, cefr_level)
            VALUES (?, ?, ?);
        """, (sc["title"], sc["topic"], sc["cefr_level"]))
        tree_id = cursor.lastrowid

        local_node_map = {}
        for node in sc["nodes"]:
            # Ensure text_en is in sentences table
            cursor.execute("""
                INSERT OR IGNORE INTO sentences (text_en, text_vi, difficulty_score, cefr_level, audio_path, source)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (node["text_en"], node["text_vi"], 2.0, sc["cefr_level"], f"dialogue_tree_{tree_id}_node_{node['node_index']}.mp3", "DialogueTree"))

            cursor.execute("SELECT id FROM sentences WHERE text_en = ?;", (node["text_en"],))
            s_row = cursor.fetchone()
            sent_id = s_row[0] if s_row else 1

            parent_db_id = local_node_map.get(node.get("parent_index"))

            cursor.execute("""
                INSERT INTO dialogue_nodes (tree_id, parent_node_id, sentence_id, speaker_role, choice_label)
                VALUES (?, ?, ?, ?, ?);
            """, (tree_id, parent_db_id, sent_id, node["speaker_role"], node["choice_label"]))
            node_db_id = cursor.lastrowid
            local_node_map[node["node_index"]] = node_db_id

    conn.commit()
    logger.info("   [4D] Built %d dialogue trees and nodes with dynamic sentence links.", len(scenarios))

    # 4E. Speed Reflex Drill Cards Generation
    logger.info("   [4E] Generating Speed Reflex Drill Cards...")
    cursor.execute("SELECT count(*) FROM reflex_drills;")
    existing_drills = cursor.fetchone()[0]

    if existing_drills > 1000 and not args.force_reset:
        logger.info("   [4E] %s reflex drill cards already exist. Skipping drill generation.", f"{existing_drills:,}")
    else:
        cursor.execute("SELECT id, text_en, text_vi, cefr_level FROM sentences;")
        stored_sentences = cursor.fetchall()

        # Fetch sentence pool for distractors
        sentence_pool = [{"id": r[0], "text_en": r[1], "text_vi": r[2], "cefr_level": r[3]} for r in stored_sentences]
        reflex_builder = ReflexBuilder(sentence_pool=sentence_pool)

        reflex_count = 0
        for sent_dict in sentence_pool:
            drill = reflex_builder.build_drill(sent_dict, drill_type="speed_translation")
            cursor.execute("""
                INSERT INTO reflex_drills (sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (drill["sentence_id"], drill["drill_type"], drill["prompt_text"], drill["correct_answer"], drill["distractors_json"], drill["target_time_ms"]))
            reflex_count += 1

            if reflex_count % 5000 == 0:
                logger.info("   -> Generated %s reflex drill cards...", f"{reflex_count:,}")

        conn.commit()
        logger.info("   [4E] Completed %s reflex drill cards.", f"{reflex_count:,}")

    # 4F. Physical MP3 Audio Generation via Edge-TTS
    logger.info("   [4F] Generating Physical MP3 Audio Files via Edge-TTS...")
    async def generate_sample_audio_files():
        audio_gen = AudioGenerator()
        cursor.execute("SELECT id, text_en FROM sentences LIMIT 100;")
        sents = cursor.fetchall()
        tasks = [audio_gen.generate_dual_speed_sentence(s_id, t_en) for s_id, t_en in sents]
        await asyncio.gather(*tasks)

    try:
        asyncio.run(generate_sample_audio_files())
        logger.info("   [4F] Generated physical MP3 audio files in data/audio/")
    except Exception as e:
        logger.warning("   [4F] Audio generation warning: %s", e)

    # 4G. Multi-Word Expressions (Idioms, Phrasal Verbs, Proverbs)
    logger.info("   [4G] Building Multi-Word Expression Database...")
    phrase_stats = run_phrase_step(db_manager, args)
    logger.info("   [4G] Completed: %s phrases, %s example sentence links.",
                f"{phrase_stats['phrases']:,}", f"{phrase_stats['links']:,}")

    # 4H. Lexical Relations & Topics (Synonyms, Antonyms, Hypernyms, Hyponyms, Topics)
    logger.info("   [4H] Building Lexical Relations & Topics Database...")
    relation_stats = run_relations_step(db_manager, args)
    logger.info("   [4H] Completed: %s relations, %s inverse links, %s topic assignments.",
                f"{relation_stats['relations']:,}", f"{relation_stats['links']:,}", f"{relation_stats['topics']:,}")

    # 4I. Vietnamese Translation Quality & Backfill
    logger.info("   [4I] Building Vietnamese Translation Backfill...")
    vi_stats = run_vietnamese_step(db_manager, args)
    logger.info("   [4I] Completed: %s definitions, %s collocations, %s phrases translated.",
                f"{vi_stats['definitions']:,}", f"{vi_stats['collocations']:,}", f"{vi_stats['phrases']:,}")

    # Step 5: Export & Optimize SQLite Mobile DB
    logger.info("[Step 5/5] Packaging & Optimizing SQLite Mobile Database...")
    exporter = SQLiteExporter(EXPORT_SQLITE_PATH)
    export_info = exporter.optimize_and_package()

    avg_speed = exporter.benchmark_reflex_query_speed(iterations=20)
    logger.info("   -> Reflex Query Benchmark Speed: %.2f ms", avg_speed)

    if args.build_core_pack:
        logger.info("[Step 6/6] Building Core 3000 Word Pack...")
        pack_stats = run_core_pack_step(db_manager, args)
        logger.info("[Step 6/6] Completed: %s words, %s quarantined.",
                    f"{pack_stats['selected']:,}", pack_stats["quarantined"])

    db_manager.close()
    elapsed = round(time.time() - start_time, 2)
    logger.info("==========================================================")
    logger.info("   PIPELINE COMPLETED SUCCESSFULLY IN %s SECONDS!         ", elapsed)
    logger.info("   Output Database: %s (%s MB)                            ", export_info["path"], export_info["size_mb"])
    logger.info("==========================================================")


if __name__ == "__main__":
    run_pipeline()
