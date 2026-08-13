"""
Configuration and Environment Settings for English Dataset Pipeline.
"""

from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
AUDIO_DIR = DATA_DIR / "audio"
OUTPUT_DIR = DATA_DIR / "output"

# Source File Paths
KAIKKI_JSON_PATH = RAW_DATA_DIR / "kaikki.org-dictionary-English.json"
TATOEBA_SENTENCES_PATH = RAW_DATA_DIR / "sentences.csv"
TATOEBA_LINKS_PATH = RAW_DATA_DIR / "links.csv"
OPUS_SUBTITLES_PATH = RAW_DATA_DIR / "opensubtitles_en_vi.txt"
SUBTLEX_FREQ_PATH = RAW_DATA_DIR / "SUBTLEX_US.csv"
NGSL_PATH = RAW_DATA_DIR / "NGSL-1.01.csv"

# Parallel sentence corpora (Phase A — sentences coverage)
OPENSUBTITLES_EN_VI_ZIP = RAW_DATA_DIR / "opensubtitles_envi" / "en-vi.txt.zip"
OPENSUBTITLES_EN = RAW_DATA_DIR / "opensubtitles_envi" / "en-vi.txt.en"
OPENSUBTITLES_VI = RAW_DATA_DIR / "opensubtitles_envi" / "en-vi.txt.vi"
ENVICORPORA_DIR = RAW_DATA_DIR / "envicorpora"
ENVICORPORA_TED_LIKE_EN = ENVICORPORA_DIR / "ted-like" / "data.en"
ENVICORPORA_TED_LIKE_VI = ENVICORPORA_DIR / "ted-like" / "data.vi"
ENVICORPORA_BASIC_EN = ENVICORPORA_DIR / "basic" / "data.en"
ENVICORPORA_BASIC_VI = ENVICORPORA_DIR / "basic" / "data.vi"
SENTENCE_LINK_CHECKPOINT = PROCESSED_DATA_DIR / "sentence_link_checkpoint.json"
KAIKKI_INGEST_CHECKPOINT = PROCESSED_DATA_DIR / ".kaikki_ingest_done"
TATOEBA_INGEST_CHECKPOINT = PROCESSED_DATA_DIR / ".tatoeba_ingest_done"

# Per-corpus ingest cap: huge parallel corpora (e.g. OpenSubtitles 37M lines)
# would blow past the plan's >=100K goal and fill the disk. Stop after this many
# accepted sentences per corpus (500K >> enough for 95% coverage of 3K core words).
MAX_SENTENCES_PER_CORPUS = 500_000

# Target Export Database Path
EXPORT_SQLITE_PATH = OUTPUT_DIR / "english_dataset.db"
STAGING_DUCKDB_PATH = PROCESSED_DATA_DIR / "staging.duckdb"

# Pipeline Parameters
BATCH_SIZE = 1000
SPACY_BATCH_SIZE = 500
MAX_CONCURRENT_AUDIO = 5
AUDIO_RETRY_COUNT = 3

# Learning Engine Default Parameters
TARGET_REFLEX_TIME_MS = 2500
DEFAULT_CEFR_LEVEL = "B1"

# Voice Settings for Edge-TTS
TTS_VOICES = {
    "US_FEMALE": "en-US-AriaNeural",
    "US_MALE": "en-US-GuyNeural",
    "UK_FEMALE": "en-GB-SoniaNeural"
}
TTS_SPEED_STANDARD = "+0%"
TTS_SPEED_FAST_REFLEX = "+20%"

# Ensure directories exist
for directory in [DATA_DIR, RAW_DATA_DIR, PROCESSED_DATA_DIR, AUDIO_DIR, OUTPUT_DIR]:
    directory.mkdir(parents=True, exist_ok=True)
