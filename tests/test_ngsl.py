"""
Tests for NGSL (New General Service List) download + loader.
"""

from pathlib import Path

from scripts.download_raw_data import load_ngsl_words


def test_load_ngsl_words_parses_csv(tmp_path: Path):
    ngsl_file = tmp_path / "NGSL-1.01.csv"
    # NGSL CSV: headword in first column, inflected forms in subsequent columns
    ngsl_file.write_text(
        "the,,,,,\n"
        "be,am,is,are,,,\n"
        "take,takes,took,taken,,\n",
        encoding="utf-8",
    )
    words = load_ngsl_words(ngsl_file)
    assert words == {"the", "be", "take"}


def test_load_ngsl_words_missing_file_returns_empty(tmp_path: Path):
    assert load_ngsl_words(tmp_path / "does-not-exist.csv") == set()