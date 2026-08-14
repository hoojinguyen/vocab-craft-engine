"""
Downloader script for raw dataset files (Kaikki, Tatoeba & SUBTLEX Frequency Data).
Downloads and extracts raw dataset files into data/raw/ directory.
"""

import sys
import os
import shutil
import tarfile
import zipfile
import urllib.request
import csv
import logging
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    KAIKKI_JSON_PATH,
    NGSL_PATH,
    OXFORD_3000_PATH,
    RAW_DATA_DIR,
    SUBTLEX_FREQ_PATH,
    TATOEBA_LINKS_PATH,
    TATOEBA_SENTENCES_PATH,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

URL_KAIKKI = "https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl"
URL_TATOEBA_SENTENCES = "https://downloads.tatoeba.org/exports/sentences.tar.bz2"
URL_TATOEBA_LINKS = "https://downloads.tatoeba.org/exports/links.tar.bz2"
URL_FREQ_WORDS = "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/en/en_50k.txt"
URL_NGSL = "https://raw.githubusercontent.com/koba-ninkigumi/ngsl/master/NGSL-1.01.csv"
OXFORD_3000_URLS = [
    "https://gist.githubusercontent.com/dlants/d3b25b0f6c0bf8d023f65e86498bf9e6/raw/3000-words.txt",
    "https://raw.githubusercontent.com/gokhanyavas/Oxford-3000-Word-List/master/Oxford%203000%20Word%20List.txt",
]
URL_OXFORD_3000 = OXFORD_3000_URLS[0]
URL_OPENS_ENVI = "https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2024/moses/en-vi.txt.zip"
URL_TED_LIKE_EN = "https://raw.githubusercontent.com/thanhleha-kit/EnViCorpora/master/ted-like/data.en"
URL_TED_LIKE_VI = "https://raw.githubusercontent.com/thanhleha-kit/EnViCorpora/master/ted-like/data.vi"
URL_BASIC_EN = "https://raw.githubusercontent.com/thanhleha-kit/EnViCorpora/master/basic/data.en"
URL_BASIC_VI = "https://raw.githubusercontent.com/thanhleha-kit/EnViCorpora/master/basic/data.vi"
OPENSUBTITLES_ZIP_MIN_SIZE = 900_000_000


def download_file(url: str, dest_path: Path):
    logger.info("Downloading %s -> %s...", url, dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    def report_progress(block_num, block_size, total_size):
        read_bytes = block_num * block_size
        if total_size > 0:
            percent = min(100, read_bytes * 100 / total_size)
            sys.stdout.write(f"\rDownloading {dest_path.name}: {percent:.1f}% ({read_bytes/(1024*1024):.1f}/{total_size/(1024*1024):.1f} MB)")
        else:
            sys.stdout.write(f"\rDownloading {dest_path.name}: {read_bytes/(1024*1024):.1f} MB")
        sys.stdout.flush()

    urllib.request.urlretrieve(url, dest_path, reporthook=report_progress)
    print()
    logger.info("Successfully downloaded %s", dest_path.name)


def extract_tar_bz2(tar_path: Path, target_filename: str):
    logger.info("Extracting %s from %s...", target_filename, tar_path.name)
    with tarfile.open(tar_path, "r:bz2") as tar:
        for member in tar.getmembers():
            if member.name.endswith(target_filename) or member.name == target_filename:
                member.name = target_filename
                tar.extract(member, path=RAW_DATA_DIR)
                logger.info("Extracted %s to %s", target_filename, RAW_DATA_DIR / target_filename)
                return
    logger.warning("Could not find %s inside %s", target_filename, tar_path.name)


def download_subtlex_frequency_data():
    """Downloads frequency words and creates SUBTLEX_US.csv if missing or small."""
    if not SUBTLEX_FREQ_PATH.exists() or SUBTLEX_FREQ_PATH.stat().st_size < 1000:
        logger.info("Downloading word frequency dataset for CEFR grading...")
        temp_txt = RAW_DATA_DIR / "freq_50k.txt"
        download_file(URL_FREQ_WORDS, temp_txt)
        
        logger.info("Converting frequency dataset to %s...", SUBTLEX_FREQ_PATH.name)
        with open(temp_txt, "r", encoding="utf-8") as f_in, \
             open(SUBTLEX_FREQ_PATH, "w", encoding="utf-8", newline="") as f_out:
            writer = csv.writer(f_out)
            writer.writerow(["Word", "FREQcount", "SUBTLWF", "Lg10WF", "SUBTLKW", "Lg10KW", "rank"])
            
            rank = 1
            for line in f_in:
                parts = line.strip().split()
                if parts:
                    word = parts[0].lower()
                    count = parts[1] if len(parts) > 1 else "1000"
                    writer.writerow([word, count, "10.0", "3.0", count, "3.0", str(rank)])
                    rank += 1
        
        if temp_txt.exists():
            temp_txt.unlink()
        logger.info("Successfully generated SUBTLEX frequency file with %d ranked words!", rank - 1)


def load_ngsl_words(path: Path) -> set:
    """
    Parses an NGSL CSV file into the set of headword lemmas.
    Format: first column is the headword, later columns are inflected forms.
    Returns an empty set when the file is missing.
    """
    if not path.exists():
        return set()
    words = set()
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            parts = line.strip().split(",")
            headword = parts[0].strip().lower() if parts else ""
            if headword:
                words.add(headword)
    return words


def download_ngsl():
    """Downloads the NGSL headword CSV if missing. NGSL is public domain."""
    if not NGSL_PATH.exists() or NGSL_PATH.stat().st_size == 0:
        download_file(URL_NGSL, NGSL_PATH)
    return NGSL_PATH


def load_oxford_words(path: Path) -> set:
    """
    Parses an Oxford 3000 text file (one word per line) into a set of lowercase words.
    Returns an empty set when the file is missing.
    """
    if not path.exists():
        return set()
    words = set()
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            word = line.strip().lower()
            if word and not word.startswith("#"):
                words.add(word)
    return words


def download_oxford_3000(dest_path: Path | None = None) -> Path:
    """
    Downloads the Oxford 3000 vocabulary list if missing.
    Tries multiple mirror URLs, falling back to basic headword list if all fail.
    """
    target = dest_path or OXFORD_3000_PATH
    if not target.exists() or target.stat().st_size == 0:
        logger.info("Downloading Oxford 3000 vocabulary list...")
        downloaded = False
        for url in OXFORD_3000_URLS:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status == 200:
                        content = resp.read()
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(content)
                        logger.info("Successfully downloaded Oxford 3000 list from %s (%d bytes)", url, len(content))
                        downloaded = True
                        break
            except Exception as e:
                logger.warning("Could not download Oxford 3000 from URL %s: %s", url, e)

        if not downloaded:
            logger.warning("All Oxford 3000 mirror URLs failed; writing local fallback list")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("the\nbe\nto\nof\nand\na\nin\nthat\nhave\ni\nit\nfor\nnot\non\nwith\nhe\nas\nyou\ndo\nat\n", encoding="utf-8")
    return target


def download_nltk_corpora(target_dir: Path | None = None) -> list[str]:
    """Checks and downloads NLTK corpora directly into local workspace directory."""
    from config.settings import NLTK_DATA_DIR, VENV_NLTK_DATA_DIR

    dest = target_dir or (VENV_NLTK_DATA_DIR if VENV_NLTK_DATA_DIR.exists() else NLTK_DATA_DIR)
    dest.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading NLTK corpora to %s...", dest)

    packages = [
        "wordnet",
        "cmudict",
        "averaged_perceptron_tagger_eng",
        "omw-1.4",
        "punkt_tab",
    ]
    downloaded = []
    try:
        import nltk

        for pkg in packages:
            try:
                nltk.download(pkg, download_dir=str(dest), quiet=True)
                downloaded.append(pkg)
            except Exception as e:
                logger.warning("Failed downloading NLTK package '%s': %s", pkg, e)
    except ImportError:
        logger.warning("NLTK not installed; skipping NLTK download")
    return downloaded


def install_argos_models() -> bool:
    """Checks and installs Argos Translate English to Vietnamese offline package."""
    try:
        import argostranslate.package
        import argostranslate.translate

        installed_languages = argostranslate.translate.get_installed_languages()
        from_lang = next((lang for lang in installed_languages if lang.code == "en"), None)
        to_lang = next((lang for lang in installed_languages if lang.code == "vi"), None)

        if from_lang and to_lang:
            translations = from_lang.get_translations(to_lang)
            if translations:
                logger.info("Argos Translate en->vi translation package is already installed.")
                return True

        logger.info("Updating Argos Translate package index...")
        argostranslate.package.update_package_index()
        available_packages = argostranslate.package.get_available_packages()
        package_to_install = next(
            (p for p in available_packages if p.from_code == "en" and p.to_code == "vi"),
            None,
        )

        if package_to_install:
            logger.info("Installing Argos Translate en->vi package...")
            download_path = package_to_install.download()
            argostranslate.package.install_from_path(download_path)
            logger.info("Successfully installed Argos Translate en->vi model!")
            return True
        else:
            logger.warning("Argos Translate en->vi package not found in index.")
            return False
    except Exception as e:
        logger.warning("Could not auto-install Argos Translate offline models: %s", e)
        return False



def download_resumable(url: str, dest_path: Path):
    """
    Resumes a download with HTTP Range; callers decide when to skip.

    If the server ignores the Range header and returns a 200 full body while a
    partial file already exists, the partial file is truncated and rewritten from
    scratch so it cannot be silently corrupted. A 416 (range start == full size)
    raises HTTPError, so callers must ensure only a smaller partial file exists.
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    existing = dest_path.stat().st_size if dest_path.exists() else 0
    request = urllib.request.Request(url, headers={"Range": f"bytes={existing}-"})
    with urllib.request.urlopen(request) as resp:
        if resp.status == 200 and existing > 0:
            logger.warning("Server ignored Range request for %s; restarting from scratch", dest_path.name)
            with open(dest_path, "wb") as f:
                shutil.copyfileobj(resp, f)
        else:
            with open(dest_path, "ab") as f:
                shutil.copyfileobj(resp, f)
    logger.info("Downloaded %s (%.1f MB)", dest_path.name, dest_path.stat().st_size / 1e6)


def extract_zip_member(zip_path: Path, out_dir: Path, member_name: str, target_name: str = None):
    """
    Extracts a member from a zip archive.

    With target_name set, the member is read and written to out_dir / target_name,
    which lets callers remap archive member names that differ from the desired
    output file name. With target_name None the member is extracted under its
    own name.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if target_name is None:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extract(member_name, out_dir)
        return
    with zipfile.ZipFile(zip_path) as zf:
        data = zf.read(member_name)
    (out_dir / target_name).write_bytes(data)


def download_opensubtitles_envi():
    from config.settings import OPENSUBTITLES_EN_VI_ZIP, OPENSUBTITLES_EN, OPENSUBTITLES_VI

    if OPENSUBTITLES_EN.exists() and OPENSUBTITLES_EN.stat().st_size > 0 \
            and OPENSUBTITLES_VI.exists() and OPENSUBTITLES_VI.stat().st_size > 0:
        return
    if not OPENSUBTITLES_EN_VI_ZIP.exists() or OPENSUBTITLES_EN_VI_ZIP.stat().st_size < OPENSUBTITLES_ZIP_MIN_SIZE:
        free_bytes = shutil.disk_usage(RAW_DATA_DIR).free
        if free_bytes < 4_000_000_000:
            logger.warning("Only %.1f GB free — OpenSubtitles corpus needs ~1GB; download may fail.", free_bytes / 1e9)
        download_resumable(URL_OPENS_ENVI, OPENSUBTITLES_EN_VI_ZIP)
    extract_zip_member(OPENSUBTITLES_EN_VI_ZIP, OPENSUBTITLES_EN_VI_ZIP.parent, "OpenSubtitles.en-vi.en", "en-vi.txt.en")
    extract_zip_member(OPENSUBTITLES_EN_VI_ZIP, OPENSUBTITLES_EN_VI_ZIP.parent, "OpenSubtitles.en-vi.vi", "en-vi.txt.vi")


def download_envicorpora():
    from config.settings import (
        ENVICORPORA_BASIC_EN, ENVICORPORA_BASIC_VI, ENVICORPORA_TED_LIKE_EN, ENVICORPORA_TED_LIKE_VI,
    )
    pairs = [
        (URL_TED_LIKE_EN, ENVICORPORA_TED_LIKE_EN),
        (URL_TED_LIKE_VI, ENVICORPORA_TED_LIKE_VI),
        (URL_BASIC_EN, ENVICORPORA_BASIC_EN),
        (URL_BASIC_VI, ENVICORPORA_BASIC_VI),
    ]
    for url, dest in pairs:
        if not dest.exists() or dest.stat().st_size == 0:
            download_resumable(url, dest)


def download_all_raw_data():
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Download Tatoeba Sentences
    if not TATOEBA_SENTENCES_PATH.exists() or TATOEBA_SENTENCES_PATH.stat().st_size == 0:
        tar_sentences = RAW_DATA_DIR / "sentences.tar.bz2"
        download_file(URL_TATOEBA_SENTENCES, tar_sentences)
        extract_tar_bz2(tar_sentences, "sentences.csv")
        if tar_sentences.exists():
            tar_sentences.unlink()

    # 2. Download Tatoeba Links
    if not TATOEBA_LINKS_PATH.exists() or TATOEBA_LINKS_PATH.stat().st_size == 0:
        tar_links = RAW_DATA_DIR / "links.tar.bz2"
        download_file(URL_TATOEBA_LINKS, tar_links)
        extract_tar_bz2(tar_links, "links.csv")
        if tar_links.exists():
            tar_links.unlink()

    # 3. Download Kaikki Dictionary
    if not KAIKKI_JSON_PATH.exists() or KAIKKI_JSON_PATH.stat().st_size == 0:
        download_file(URL_KAIKKI, KAIKKI_JSON_PATH)

    # 4. Download / Generate SUBTLEX frequency file
    download_subtlex_frequency_data()

    # 5. Download NGSL validation word list
    download_ngsl()

    # 6. Download OpenSubtitles en-vi parallel corpus (951MB)
    download_opensubtitles_envi()

    # 7. Download EnViCorpora (ted-like + basic)
    download_envicorpora()

    # 8. Download Oxford 3000 list
    download_oxford_3000()

    # 9. Download NLTK corpora (wordnet, cmudict, averaged_perceptron_tagger_eng, omw-1.4, punkt_tab)
    download_nltk_corpora()

    # 10. Install Argos Translate offline translation models (en -> vi)
    install_argos_models()

    logger.info("All raw data files are ready in %s!", RAW_DATA_DIR)


if __name__ == "__main__":
    download_all_raw_data()
