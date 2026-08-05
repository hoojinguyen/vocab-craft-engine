import pytest

from src.ingestion.sentence_filter import SentenceFilter

sf = SentenceFilter()


def test_accepts_normal_pair():
    assert sf.is_clean_pair("Where are you going?", "Bạn đang đi đâu thế?")


def test_rejects_too_short_or_long():
    assert not sf.is_clean_pair("Hi", "Chào")            # 1 word
    long_en = " ".join(["word"] * 31)
    assert not sf.is_clean_pair(long_en, "dịch dài")      # 31 words


def test_rejects_bad_first_char():
    assert not sf.is_clean_pair("- Hello there.", "Chào nhé.")


def test_rejects_empty_or_passthrough_vi():
    assert not sf.is_clean_pair("Hello there.", "")
    assert not sf.is_clean_pair("Hello there.", "Hello there.")  # untranslated


def test_rejects_subtitle_noise():
    assert not sf.is_clean_pair("♪ Singing now ♪", "Đang hát")
    assert not sf.is_clean_pair("[Music playing]", "Nhạc")
    assert not sf.is_clean_pair("(Laughing)", "Cười")
    assert not sf.is_clean_pair("*Whispering*", "Thì thầm")


def test_rejects_digit_heavy():
    assert not sf.is_clean_pair("Call me at 5551234 now", "Gọi tôi số 5551234")


def test_rejects_uppercase_name_labels():
    assert not sf.is_clean_pair("JOHN: Hello there.", "JOHN: Xin chào.")
