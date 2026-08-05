from src.ingestion.opus_parser import ParallelCorpusParser


def test_parses_moses_side_by_side(tmp_path):
    en = tmp_path / "data.en"; vi = tmp_path / "data.vi"
    en.write_text("Hello there.\nHow are you?\n", encoding="utf-8")
    vi.write_text("Xin chào.\nBạn khỏe không?\n", encoding="utf-8")
    pairs = list(ParallelCorpusParser(en, vi, source="TED-EnVi").parse_pairs())
    assert pairs == [
        {"text_en": "Hello there.", "text_vi": "Xin chào.", "source": "TED-EnVi"},
        {"text_en": "How are you?", "text_vi": "Bạn khỏe không?", "source": "TED-EnVi"},
    ]


def test_dedupes_normalized_pairs(tmp_path):
    en = tmp_path / "data.en"; vi = tmp_path / "data.vi"
    en.write_text("Hello there.\nhello there.\n", encoding="utf-8")
    vi.write_text("Xin chào.\nXin chào.\n", encoding="utf-8")
    pairs = list(ParallelCorpusParser(en, vi).parse_pairs())
    assert len(pairs) == 1


def test_skips_mismatched_line_counts(tmp_path):
    en = tmp_path / "data.en"; vi = tmp_path / "data.vi"
    en.write_text("One line only.\n", encoding="utf-8")
    vi.write_text("", encoding="utf-8")
    assert list(ParallelCorpusParser(en, vi).parse_pairs()) == []