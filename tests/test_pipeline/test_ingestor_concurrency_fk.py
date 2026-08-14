import concurrent.futures
from pathlib import Path
from src.db.duckdb_manager import DuckDBManager
from src.ingestion.kaikki_ingestor import KaikkiIngestor
from src.ingestion.wordnet_ingestor import WordNetIngestor
from src.transform.relation_builder import RelationBuilder
from src.transform.sentence_linker import SentenceLinker
from src.transform.phrase_extractor import PhraseExtractor
from src.transform.topic_mapper import TopicMapper


def test_concurrent_kaikki_and_wordnet_fk_integrity(tmp_path: Path):
    db_path = tmp_path / "fk_test.duckdb"
    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    # Create dummy Kaikki jsonl file with 500 entries
    kaikki_file = tmp_path / "dummy_kaikki.jsonl"
    lines = []
    for i in range(500):
        lines.append(f'{{"word": "word_{i}", "pos": "noun", "lang": "English", "senses": [{{"glosses": ["def for word_{i}"]}}]}}\n')
    kaikki_file.write_text("".join(lines), encoding="utf-8")

    kaikki_ingestor = KaikkiIngestor()
    wordnet_ingestor = WordNetIngestor()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(kaikki_ingestor.ingest, db_mgr, kaikki_file)
        f2 = executor.submit(wordnet_ingestor.ingest, db_mgr, limit=100)
        f1.result()
        f2.result()

    # Verify 0 orphaned definitions
    orphaned_defs = db_mgr.fetch_one("SELECT count(*) FROM definitions WHERE word_id NOT IN (SELECT id FROM words)")[0]
    assert orphaned_defs == 0

    # Verify 0 orphaned word_relations
    orphaned_rels = db_mgr.fetch_one("SELECT count(*) FROM word_relations WHERE word_id NOT IN (SELECT id FROM words)")[0]
    assert orphaned_rels == 0

    # Verify 0 orphaned target_word_id in word_relations
    orphaned_targets = db_mgr.fetch_one(
        "SELECT count(*) FROM word_relations WHERE target_word_id IS NOT NULL AND target_word_id NOT IN (SELECT id FROM words)"
    )[0]
    assert orphaned_targets == 0

    db_mgr.close()


def test_concurrent_transformers_thread_safety(tmp_path: Path):
    db_path = tmp_path / "transform_fk_test.duckdb"
    db_mgr = DuckDBManager(db_path)
    db_mgr.init_schema()

    # Seed data
    db_mgr.insert_batch_fast("words", [
        {"lemma": "run", "pos": "verb", "source": "test"},
        {"lemma": "jog", "pos": "verb", "source": "test"},
        {"lemma": "doctor", "pos": "noun", "source": "test"},
        {"lemma": "give up", "pos": "verb", "source": "test"},
    ])
    db_mgr.insert_batch_fast("sentences", [
        {"text_en": "The doctor had to give up jogging.", "source": "tatoeba"},
        {"text_en": "She went for a fast run.", "source": "tatoeba"},
    ])
    db_mgr.insert_batch_fast("definitions", [
        {"word_id": 1, "definition_en": "to move swiftly on foot", "source": "test"},
        {"word_id": 3, "definition_en": "a medical professional", "source": "test"},
    ])
    db_mgr.insert_batch_fast("word_relations", [
        {"word_id": 1, "relation_type": "synonym", "target_text": "jog", "target_word_id": None, "source": "test"},
    ])

    relation_builder = RelationBuilder()
    sentence_linker = SentenceLinker()
    phrase_extractor = PhraseExtractor()
    topic_mapper = TopicMapper()

    # Run multiple transformers concurrently to verify no temp table collisions or lock conflicts
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        f1 = executor.submit(relation_builder.deduplicate_and_link, db_mgr)
        f2 = executor.submit(sentence_linker.link, db_mgr)
        f3 = executor.submit(phrase_extractor.extract, db_mgr)
        f4 = executor.submit(topic_mapper.map_topics, db_mgr)

        f1.result()
        f2.result()
        f3.result()
        f4.result()

    # Verify no orphaned relations, phrase_sentences, word_sentences, word_topics
    orphaned_rels = db_mgr.fetch_one("SELECT count(*) FROM word_relations WHERE word_id NOT IN (SELECT id FROM words)")[0]
    assert orphaned_rels == 0

    orphaned_targets = db_mgr.fetch_one(
        "SELECT count(*) FROM word_relations WHERE target_word_id IS NOT NULL AND target_word_id NOT IN (SELECT id FROM words)"
    )[0]
    assert orphaned_targets == 0

    orphaned_phrase_sentences = db_mgr.fetch_one(
        "SELECT count(*) FROM phrase_sentences WHERE phrase_id NOT IN (SELECT id FROM phrases) OR sentence_id NOT IN (SELECT id FROM sentences)"
    )[0]
    assert orphaned_phrase_sentences == 0

    orphaned_word_sentences = db_mgr.fetch_one(
        "SELECT count(*) FROM word_sentences WHERE word_id NOT IN (SELECT id FROM words) OR sentence_id NOT IN (SELECT id FROM sentences)"
    )[0]
    assert orphaned_word_sentences == 0

    orphaned_topics = db_mgr.fetch_one("SELECT count(*) FROM word_topics WHERE word_id NOT IN (SELECT id FROM words)")[0]
    assert orphaned_topics == 0

    db_mgr.close()
