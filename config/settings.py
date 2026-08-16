"""
Configuration and Environment Settings for English Dataset Pipeline.
"""

from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
AUDIO_DIR = DATA_DIR / "audio"
OUTPUT_DIR = DATA_DIR / "output"

PIPELINE_CONFIG_PATH = CONFIG_DIR / "pipeline_config.yaml"
THEME_MAP_PATH = CONFIG_DIR / "theme_map.yaml"


def load_pipeline_config(config_path: Path | None = None) -> dict:
    """Loads and returns the pipeline configuration YAML."""
    import yaml

    path = config_path or PIPELINE_CONFIG_PATH
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {
        "concurrency": {"max_workers": 4, "batch_size": 10000},
        "staging": {"memory_limit": "4GB", "threads": 4},
        "export": {"journal_mode": "WAL"},
        "steps": {"optional_defaults": {"enrich_audio": False}},
    }


# Source File Paths
KAIKKI_JSON_PATH = RAW_DATA_DIR / "kaikki.org-dictionary-English.json"
TATOEBA_SENTENCES_PATH = RAW_DATA_DIR / "sentences.csv"
TATOEBA_LINKS_PATH = RAW_DATA_DIR / "links.csv"
OPUS_SUBTITLES_PATH = RAW_DATA_DIR / "opensubtitles_en_vi.txt"
SUBTLEX_FREQ_PATH = RAW_DATA_DIR / "SUBTLEX_US.csv"
NGSL_PATH = RAW_DATA_DIR / "NGSL-1.01.csv"
OXFORD_3000_PATH = RAW_DATA_DIR / "oxford_3000.txt"

# Curated Open-Source Datasets V3 Paths
FVDP_DICT_PATH = RAW_DATA_DIR / "fvdp_anhviet.json"
DAILYDIALOG_PATH = RAW_DATA_DIR / "dailydialog.json"
CLOTH_DATASET_PATH = RAW_DATA_DIR / "cloth_cloze.json"
AWL_PATH = RAW_DATA_DIR / "academic_word_list.txt"

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

# V3 Vocabulary and Sentence Curation Parameters
TARGET_VOCAB_SIZE_LIMIT = 50_000
MAX_SENTENCES_PER_WORD = 3
MAX_SENTENCES_PER_CORPUS = 500_000

# Target Export Database Path
EXPORT_SQLITE_PATH = OUTPUT_DIR / "english_dataset.db"
STAGING_DUCKDB_PATH = PROCESSED_DATA_DIR / "staging.duckdb"
LEARNING_GRAPH_DUCKDB_PATH = PROCESSED_DATA_DIR / "learning_graph.duckdb"
CURRICULUM_OUTPUT_DIR = OUTPUT_DIR / "curriculum"


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
    "UK_FEMALE": "en-GB-SoniaNeural",
}
TTS_SPEED_STANDARD = "+0%"
TTS_SPEED_FAST_REFLEX = "+20%"

# Ensure directories exist
for directory in [DATA_DIR, RAW_DATA_DIR, PROCESSED_DATA_DIR, AUDIO_DIR, OUTPUT_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# NLTK local data path configuration
NLTK_DATA_DIR = RAW_DATA_DIR / "nltk_data"
VENV_NLTK_DATA_DIR = BASE_DIR / ".venv" / "nltk_data"

try:
    import nltk

    valid_paths = [str(VENV_NLTK_DATA_DIR), str(NLTK_DATA_DIR)]
    for p in nltk.data.path:
        if str(BASE_DIR) in p and p not in valid_paths:
            valid_paths.append(p)
    nltk.data.path = valid_paths
except ImportError:
    pass
