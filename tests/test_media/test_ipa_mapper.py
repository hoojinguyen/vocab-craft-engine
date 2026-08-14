from pathlib import Path
import tempfile
import pytest
from src.db.duckdb_manager import DuckDBManager
from src.media.ipa_mapper import IPAMapper


def test_ipa_mapper_tier_hierarchy():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "staging.duckdb"
        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        mapper = IPAMapper(db_mgr=db_mgr)

        # 1. Tier 1: Existing Kaikki IPA
        uk, us = mapper.get_ipa("water", existing_ipa_uk="/ˈwɔː.tər/", existing_ipa_us="/ˈwɑː.tɚ/")
        assert uk == "/ˈwɔː.tər/"
        assert us == "/ˈwɑː.tɚ/"

        # Check that it was saved into DuckDB _ipa_cache
        cached = db_mgr.lookup_ipa("water")
        assert cached is not None
        assert cached["ipa_uk"] == "/ˈwɔː.tər/"
        assert cached["ipa_us"] == "/ˈwɑː.tɚ/"
        assert cached["source"] == "kaikki"

        # 2. Tier 0: Cache Hit
        uk_c, us_c = mapper.get_ipa("water")
        assert uk_c == "/ˈwɔː.tər/"
        assert us_c == "/ˈwɑː.tɚ/"

        # 3. Tier 2: CMU Dict Lookup (e.g. "phone")
        uk_phone, us_phone = mapper.get_ipa("phone")
        assert uk_phone is not None and "f" in uk_phone
        assert us_phone is not None and "f" in us_phone

        cached_phone = db_mgr.lookup_ipa("phone")
        assert cached_phone is not None
        assert cached_phone["source"] == "cmudict"

        # 4. Tier 3: G2P Fallback for unknown word
        uk_novel, us_novel = mapper.get_ipa("chatgptification")
        assert uk_novel is not None and len(uk_novel) > 0
        assert us_novel is not None and len(us_novel) > 0

        cached_novel = db_mgr.lookup_ipa("chatgptification")
        assert cached_novel is not None
        assert cached_novel["source"] == "g2p-en"


def test_ipa_mapper_backward_compatibility():
    mapper = IPAMapper()
    ipa_str = mapper.get_ipa_string("hello", existing_ipa="/həˈloʊ/")
    assert ipa_str == "/həˈloʊ/"

    ipa_auto = mapper.get_ipa_string("banana")
    assert len(ipa_auto) > 0


def test_ipa_mapper_empty_and_whitespace():
    mapper = IPAMapper()
    assert mapper.get_ipa("") == (None, None)
    assert mapper.get_ipa(None) == (None, None)
    assert mapper.get_ipa("   ") == (None, None)

    # Word with spaces and upper case
    uk, us = mapper.get_ipa("  PHONE  ")
    assert uk is not None and "f" in uk
    assert us is not None and "f" in us


def test_ipa_mapper_single_existing_ipa():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "staging.duckdb"
        db_mgr = DuckDBManager(db_path)
        db_mgr.init_schema()

        mapper = IPAMapper(db_mgr=db_mgr)
        uk, us = mapper.get_ipa("testword", existing_ipa_uk="/tɛstwɜːd/")
        assert uk == "/tɛstwɜːd/"
        assert us == "/tɛstwɜːd/"
