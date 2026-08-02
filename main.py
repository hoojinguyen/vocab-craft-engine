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
from src.media.ipa_mapper import IPAMapper
from src.media.audio_generator import AudioGenerator
from src.export.sqlite_exporter import SQLiteExporter

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
    return parser.parse_args()


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
            "word_sentence_map", "reflex_drills", "dialogue_nodes",
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
                        "definition_vi": def_item.get("definition_vi") or def_item["definition_en"],
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
    logger.info("   [4A] Extracting & Translating Verb+Noun & Phrasal Verb Collocations...")
    chunk_extractor = ChunkExtractor()
    translator = Translator()
    cursor.execute("SELECT id, text_en FROM sentences;")
    all_sentences = cursor.fetchall()

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

    # Step 5: Export & Optimize SQLite Mobile DB
    logger.info("[Step 5/5] Packaging & Optimizing SQLite Mobile Database...")
    exporter = SQLiteExporter(EXPORT_SQLITE_PATH)
    export_info = exporter.optimize_and_package()

    avg_speed = exporter.benchmark_reflex_query_speed(iterations=20)
    logger.info("   -> Reflex Query Benchmark Speed: %.2f ms", avg_speed)

    db_manager.close()
    elapsed = round(time.time() - start_time, 2)
    logger.info("==========================================================")
    logger.info("   PIPELINE COMPLETED SUCCESSFULLY IN %s SECONDS!         ", elapsed)
    logger.info("   Output Database: %s (%s MB)                            ", export_info["path"], export_info["size_mb"])
    logger.info("==========================================================")


if __name__ == "__main__":
    run_pipeline()
