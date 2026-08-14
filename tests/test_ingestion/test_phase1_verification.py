"""
Comprehensive Phase 1 End-to-End Ingestion and Data Integrity Verification Test.

Validates:
1. Schema initialization.
2. Kaikki Wiktionary streaming ingestion with definitions and sounds.
3. WordNet synset extraction, definitions, and relations without ID hardcoding.
4. Tatoeba bidirectional sentence linking & length filtering.
5. OPUS parallel sentence ingestion.
6. SUBTLEX-US frequency rank & CEFR level annotation.
7. Foreign key and data integrity checks across all populated staging tables.
"""

import json
import pytest
from pathlib import Path

from src.db.duckdb_manager import DuckDBManager
from src.ingestion.frequency_ingestor import FrequencyIngestor
from src.ingestion.kaikki_ingestor import KaikkiIngestor
from src.ingestion.opus_ingestor import OpusIngestor
from src.ingestion.tatoeba_ingestor import TatoebaIngestor
from src.ingestion.wordnet_ingestor import WordNetIngestor


@pytest.fixture
def test_env(tmp_path: Path):
    db_file = tmp_path / "phase1_verify.duckdb"
    mgr = DuckDBManager(db_path=db_file)
    mgr.init_schema()

    # Create dummy Kaikki sample
    kaikki_file = tmp_path / "kaikki.jsonl"
    kaikki_records = [
        {
            "word": "abandon",
            "pos": "verb",
            "lang": "English",
            "sounds": [{"ipa": "/əˈbæn.dən/", "tags": ["US"]}, {"ipa": "/əˈbæn.dən/", "tags": ["UK"]}],
            "senses": [{"glosses": ["To leave behind or give up entirely."], "examples": [{"text": "They abandoned the ship."}]}],
        },
        {
            "word": "ability",
            "pos": "noun",
            "lang": "English",
            "sounds": [{"ipa": "/əˈbɪl.ə.ti/", "tags": ["US"]}],
            "senses": [{"glosses": ["The quality or state of being able; capacity to do something."]}],
        },
        {
            "word": "able",
            "pos": "adj",
            "lang": "English",
            "sounds": [{"ipa": "/ˈeɪ.bəl/", "tags": ["US"]}],
            "senses": [{"glosses": ["Having sufficient power, skill, or resources to accomplish an object."]}],
        },
    ]
    with open(kaikki_file, "w", encoding="utf-8") as f:
        for rec in kaikki_records:
            f.write(json.dumps(rec) + "\n")

    # Create dummy Tatoeba sample
    sent_file = tmp_path / "sentences.csv"
    sent_file.write_text(
        "1\teng\tThey abandoned the sinking ship immediately.\n"
        "2\tvie\tHọ đã từ bỏ con tàu đang chìm ngay lập tức.\n"
        "3\tvie\tCô ấy có khả năng học ngôn ngữ rất nhanh.\n"
        "4\teng\tShe has the ability to learn languages quickly.\n"
        "5\tfra\tIgnored french sentence.\n"
        "6\tdeu\tIgnored german sentence.\n",
        encoding="utf-8",
    )
    links_file = tmp_path / "links.csv"
    links_file.write_text("1\t2\n3\t4\n5\t6\n", encoding="utf-8")

    # Create dummy OPUS sample
    opus_en = tmp_path / "opus.en"
    opus_vi = tmp_path / "opus.vi"
    opus_en.write_text(
        "We are able to accomplish this task together.\n"
        "Short\n"
        "Knowledge and perseverance give you great power.\n",
        encoding="utf-8",
    )
    opus_vi.write_text(
        "Chúng ta có thể hoàn thành nhiệm vụ này cùng nhau.\n"
        "Ngắn\n"
        "Kiến thức và sự kiên trì cho bạn sức mạnh to lớn.\n",
        encoding="utf-8",
    )

    # Create dummy SUBTLEX-US sample
    subtlex_file = tmp_path / "SUBTLEX_US.csv"
    subtlex_file.write_text(
        "Word,FREQcount,SUBTLWF,Lg10WF,SUBTLKW,Lg10KW,rank\n"
        "able,50000,10.0,4.7,5000,4.7,450\n"
        "ability,15000,5.0,4.2,2000,4.2,1200\n"
        "abandon,3000,1.0,3.5,500,3.5,4200\n",
        encoding="utf-8",
    )

    yield {
        "mgr": mgr,
        "kaikki_file": kaikki_file,
        "sent_file": sent_file,
        "links_file": links_file,
        "opus_en": opus_en,
        "opus_vi": opus_vi,
        "subtlex_file": subtlex_file,
    }

    mgr.close()


def test_phase1_complete_ingestion_verification(test_env):
    mgr: DuckDBManager = test_env["mgr"]
    conn = mgr.get_connection()

    # 1. Run Kaikki Ingestion
    kaikki_ingestor = KaikkiIngestor()
    kaikki_count = kaikki_ingestor.ingest(mgr, test_env["kaikki_file"])
    assert kaikki_count == 3
    assert mgr.count_rows("words") == 3
    assert mgr.count_rows("definitions") == 3

    # 2. Run WordNet Ingestion
    wordnet_ingestor = WordNetIngestor()
    wordnet_count = wordnet_ingestor.ingest(mgr, limit=150)
    assert wordnet_count > 0
    assert mgr.count_rows("words") > 3
    assert mgr.count_rows("definitions") > 3
    assert mgr.count_rows("word_relations") > 0

    # 3. Run Tatoeba Ingestion (2-way links)
    tatoeba_ingestor = TatoebaIngestor()
    tatoeba_count = tatoeba_ingestor.ingest_files(mgr, test_env["sent_file"], test_env["links_file"])
    assert tatoeba_count == 2
    assert mgr.count_rows("sentences") == 2

    # 4. Run OPUS Ingestion
    opus_ingestor = OpusIngestor()
    opus_count = opus_ingestor.ingest_pair(mgr, test_env["opus_en"], test_env["opus_vi"], source="opus")
    assert opus_count == 2
    assert mgr.count_rows("sentences") == 4

    # 5. Run SUBTLEX Frequency & CEFR Ingestion
    freq_ingestor = FrequencyIngestor()
    freq_updated = freq_ingestor.populate_frequency_ranks(mgr, test_env["subtlex_file"])
    assert freq_updated >= 3

    # --- Verification Checks ---

    # A. Verify Frequency Ranks and CEFR Levels
    word_able = conn.execute("SELECT frequency_rank, cefr_level FROM words WHERE lemma = 'able' AND pos = 'adj'").fetchone()
    assert word_able is not None
    assert word_able[0] == 450
    assert word_able[1] == "A1"

    word_ability = conn.execute("SELECT frequency_rank, cefr_level FROM words WHERE lemma = 'ability' AND pos = 'noun'").fetchone()
    assert word_ability is not None
    assert word_ability[0] == 1200
    assert word_ability[1] == "A2"

    word_abandon = conn.execute("SELECT frequency_rank, cefr_level FROM words WHERE lemma = 'abandon' AND pos = 'verb'").fetchone()
    assert word_abandon is not None
    assert word_abandon[0] == 4200
    assert word_abandon[1] == "B2"

    # B. Verify WordNet relations do not contain hardcoded word_id = 1
    relations = conn.execute("SELECT DISTINCT word_id FROM word_relations").fetchall()
    word_ids_in_relations = {r[0] for r in relations}
    assert len(word_ids_in_relations) > 10, f"Expected varied word_ids in relations, got {word_ids_in_relations}"

    # C. Verify Foreign Key Integrity: All definitions.word_id exist in words.id
    orphan_defs = conn.execute("""
        SELECT count(*) FROM definitions d
        LEFT JOIN words w ON d.word_id = w.id
        WHERE w.id IS NULL
    """).fetchone()[0]
    assert orphan_defs == 0, f"Found {orphan_defs} orphaned definitions!"

    # D. Verify Foreign Key Integrity: All word_relations.word_id exist in words.id
    orphan_rels = conn.execute("""
        SELECT count(*) FROM word_relations r
        LEFT JOIN words w ON r.word_id = w.id
        WHERE w.id IS NULL
    """).fetchone()[0]
    assert orphan_rels == 0, f"Found {orphan_rels} orphaned word_relations!"

    # E. Verify Target Word IDs: All non-null target_word_id exist in words.id
    orphan_targets = conn.execute("""
        SELECT count(*) FROM word_relations r
        LEFT JOIN words w ON r.target_word_id = w.id
        WHERE r.target_word_id IS NOT NULL AND w.id IS NULL
    """).fetchone()[0]
    assert orphan_targets == 0, f"Found {orphan_targets} invalid target_word_ids in word_relations!"

    # F. Verify Sentence Texts are clean and deduplicated
    sentences = conn.execute("SELECT text_en, text_vi, source FROM sentences").fetchall()
    assert len(sentences) == 4
    for sent in sentences:
        assert sent[0] and len(sent[0].split()) >= 4
        assert sent[1]
        assert sent[2] in ("tatoeba", "opus")
