from pathlib import Path
import tempfile
from unittest.mock import patch
import pytest
from scripts.download_raw_data import download_oxford_3000, download_nltk_corpora, load_oxford_words


def test_load_oxford_words_parsing():
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tmp:
        tmp.write("abandon\nability\nable\nabout\nabove\n")
        tmp_path = Path(tmp.name)

    try:
        words = load_oxford_words(tmp_path)
        assert len(words) == 5
        assert "abandon" in words
        assert "able" in words
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def test_download_oxford_3000_creates_file(tmp_path):
    dest_path = tmp_path / "oxford_3000.txt"
    with patch("scripts.download_raw_data.OXFORD_3000_PATH", dest_path):
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = b"apple\nbanana\ncherry\n"
            mock_urlopen.return_value.__enter__.return_value.status = 200
            res_path = download_oxford_3000(dest_path=dest_path)
            assert res_path.exists()
            assert "apple" in res_path.read_text(encoding="utf-8")


def test_download_nltk_corpora_calls():
    with patch("nltk.download") as mock_nltk_download:
        download_nltk_corpora()
        assert mock_nltk_download.call_count >= 2
