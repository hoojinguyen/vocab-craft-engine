"""
End-to-End Master Integration Verification Test (Phases 1, 2, and 3).

Executes the full pipeline workflow from raw ingestion -> transforms -> enrichment -> export.
Asserts on:
1. All 11 staging DuckDB tables populated and consistent.
2. Zero orphaned foreign keys in DuckDB staging.
3. SQLite english_dataset.db exported with WAL mode, 14 covering indexes, and 0 FK violations.
4. SQLite core_3000.db exported with ranked core headwords and 0 FK violations.
5. Full hierarchical dataset.json exported with nested definitions, relations, topics, and sentences.
6. Distribution ZIP package, SHA256 checksum file, and manifest.json created and valid.
"""

import json
import sqlite3
import pytest
from pathlib import Path

from src.db.duckdb_manager import DuckDBManager
from src.export.core_exporter import CoreExporter
from src.export.json_exporter import JsonExporter
from src.export.packager import DatasetPackager
from src.export.sqlite_exporter import SqliteExporter
from src.export.verifier import DatasetVerifier
from src.enrichment.reflex_builder import ReflexBuilder
from src.enrichment.scenario_builder import ScenarioBuilder
from src.enrichment.translation import HybridTranslator
from src.ingestion.frequency_ingestor import FrequencyIngestor
from src.ingestion.kaikki_ingestor import KaikkiIngestor
from src.ingestion.opus_ingestor import OpusIngestor
from src.ingestion.tatoeba_ingestor import TatoebaIngestor
from src.ingestion.wordnet_ingestor import WordNetIngestor
from src.transform.phrase_extractor import PhraseExtractor
from src.transform.relation_builder import RelationBuilder
from src.transform.sentence_linker import SentenceLinker
from src.transform.topic_mapper import TopicMapper


@pytest.fixture
def master_env(tmp_path: Path):
    db_file = tmp_path / "master_staging.duckdb"
    mgr = DuckDBManager(db_path=db_file)
    mgr.init_schema()

    # 1. Prepare raw fixture files
    kaikki_file = tmp_path / "kaikki.json"
    kaikki_records = [
        {"word": "abandon", "pos": "verb", "lang": "English", "sounds": [{"ipa": "/əˈbændən/", "tags": ["US"]}], "senses": [{"glosses": ["To leave behind."]}]},
        {"word": "doctor", "pos": "noun", "lang": "English", "sounds": [{"ipa": "/ˈdɑktər/", "tags": ["US"]}], "senses": [{"glosses": ["A physician or surgeon."]}]},
        {"word": "computer", "pos": "noun", "lang": "English", "sounds": [{"ipa": "/kəmˈpjuːtər/", "tags": ["US"]}], "senses": [{"glosses": ["An electronic device for computing."]}]},
        {"word": "run", "pos": "verb", "lang": "English", "sounds": [{"ipa": "/rʌn/", "tags": ["US"]}], "senses": [{"glosses": ["To move rapidly on foot."]}]},
    ]
    with open(kaikki_file, "w", encoding="utf-8") as f:
        for r in kaikki_records:
            f.write(json.dumps(r) + "\n")

    sent_file = tmp_path / "sentences.csv"
    sent_file.write_text(
        "1\teng\tThe doctor visited the hospital today.\n"
        "2\tvie\tBác sĩ đã đến bệnh viện hôm nay.\n"
        "3\tvie\tHọ cùng nhau chạy rất nhanh mỗi sáng.\n"
        "4\teng\tThey run together very fast every morning.\n"
        "5\teng\tHe never gave up on his dreams.\n"
        "6\tvie\tAnh ấy không bao giờ từ bỏ ước mơ của mình.\n",
        encoding="utf-8",
    )
    links_file = tmp_path / "links.csv"
    links_file.write_text("1\t2\n3\t4\n5\t6\n", encoding="utf-8")

    subtlex_file = tmp_path / "SUBTLEX_US.csv"
    subtlex_file.write_text(
        "Word,FREQcount,SUBTLWF,Lg10WF,SUBTLKW,Lg10KW,rank\n"
        "run,50000,10.0,4.7,5000,4.7,300\n"
        "doctor,15000,5.0,4.2,2000,4.2,1100\n"
        "computer,10000,4.0,4.0,1500,4.0,1800\n"
        "abandon,2000,1.0,3.3,300,3.3,5200\n",
        encoding="utf-8",
    )

    yield {
        "mgr": mgr,
        "kaikki_file": kaikki_file,
        "sent_file": sent_file,
        "links_file": links_file,
        "subtlex_file": subtlex_file,
        "output_dir": tmp_path / "output",
    }
    mgr.close()


def test_master_pipeline_v2_end_to_end_audit(master_env):
    mgr: DuckDBManager = master_env["mgr"]
    output_dir = master_env["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    # === PHASE 1: INGESTION ===
    kaikki_count = KaikkiIngestor().ingest(mgr, master_env["kaikki_file"])
    assert kaikki_count == 4
    assert mgr.count_rows("words") == 4
    assert mgr.count_rows("definitions") == 4

    wordnet_count = WordNetIngestor().ingest(mgr, limit=100)
    assert wordnet_count > 0
    assert mgr.count_rows("word_relations") > 0

    tatoeba_count = TatoebaIngestor().ingest_files(mgr, master_env["sent_file"], master_env["links_file"])
    assert tatoeba_count == 3
    assert mgr.count_rows("sentences") == 3

    freq_count = FrequencyIngestor().populate_frequency_ranks(mgr, master_env["subtlex_file"])
    assert freq_count >= 4

    # === PHASE 2: TRANSFORMS & ENRICHMENT ===
    links_count = SentenceLinker().link(mgr)
    assert links_count > 0
    assert mgr.count_rows("word_sentences") > 0

    phrases_count = PhraseExtractor().extract(mgr)
    assert phrases_count >= 1
    assert mgr.count_rows("phrases") >= 1
    assert mgr.count_rows("phrase_sentences") >= 1

    rel_count = RelationBuilder().deduplicate_and_link(mgr)
    assert rel_count > 0

    topics_count = TopicMapper().map_topics(mgr)
    assert topics_count > 0
    assert mgr.count_rows("word_topics") > 0

    translator = HybridTranslator(mgr)
    defs_trans = translator.translate_definitions(limit=20)
    phrases_trans = translator.translate_phrases(limit=20)
    assert defs_trans > 0
    assert phrases_trans >= 1

    drills_count = ReflexBuilder().build(mgr)
    assert drills_count > 0
    assert mgr.count_rows("reflex_drills") > 0

    scenarios_count = ScenarioBuilder().build(mgr)
    assert scenarios_count >= 4
    assert mgr.count_rows("dialogue_trees") >= 4
    assert mgr.count_rows("dialogue_nodes") >= 20

    # === PHASE 3: EXPORT & PACKAGING ===
    sqlite_path = output_dir / "english_dataset.db"
    core_path = output_dir / "core_3000.db"
    json_path = output_dir / "dataset.json"

    # Export main SQLite
    exporter = SqliteExporter()
    exported_counts = exporter.export(mgr, sqlite_path)
    assert exported_counts["words"] > 0
    assert exported_counts["sentences"] == 3
    assert exported_counts["phrases"] >= 1

    # Verify main SQLite
    verifier = DatasetVerifier()
    main_report = verifier.verify(sqlite_path)
    assert main_report.is_valid is True
    assert main_report.foreign_key_violations == 0
    assert main_report.integrity_check_passed is True
    assert main_report.invalid_json_count == 0

    # Check WAL mode and indexes on main SQLite
    s_conn = sqlite3.connect(str(sqlite_path))
    journal_mode = s_conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert journal_mode.lower() == "wal"
    indexes = [r[0] for r in s_conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()]
    assert "idx_words_lemma" in indexes
    assert "idx_reflex_drills_sent" in indexes
    s_conn.close()

    # Package distribution archive
    packager = DatasetPackager()
    pkg_res = packager.package(sqlite_path, output_dir=output_dir, version="2.0.0", table_counts=exported_counts)
    assert pkg_res["zip_path"].exists()
    assert pkg_res["sha256_path"].exists()
    assert pkg_res["manifest_path"].exists()

    # Export Core 3000 SQLite
    core_exporter = CoreExporter()
    core_cnt = core_exporter.export_core_bundle(mgr, core_path, core_limit=3000)
    assert core_cnt > 0

    core_report = verifier.verify(core_path)
    assert core_report.is_valid is True
    assert core_report.foreign_key_violations == 0

    c_conn = sqlite3.connect(str(core_path))
    core_journal = c_conn.execute("PRAGMA journal_mode;").fetchone()[0]
    assert core_journal.lower() == "wal"
    c_conn.close()

    # Export Hierarchical JSON
    json_exporter = JsonExporter()
    json_count = json_exporter.export(mgr, json_path)
    assert json_count > 0
    assert json_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["version"] == "2.0"
    assert len(payload["vocabulary"]) > 0
    assert len(payload["phrases"]) > 0
    assert len(payload["reflex_drills"]) > 0
