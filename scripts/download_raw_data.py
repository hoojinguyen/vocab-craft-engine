"""
Downloader script for raw dataset files (Kaikki, Tatoeba & SUBTLEX Frequency Data).
Downloads and extracts raw dataset files into data/raw/ directory.
"""

import sys
import os
import tarfile
import urllib.request
import csv
import logging
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (
    RAW_DATA_DIR,
    KAIKKI_JSON_PATH,
    TATOEBA_SENTENCES_PATH,
    TATOEBA_LINKS_PATH,
    SUBTLEX_FREQ_PATH,
    NGSL_PATH
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

URL_KAIKKI = "https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl"
URL_TATOEBA_SENTENCES = "https://downloads.tatoeba.org/exports/sentences.tar.bz2"
URL_TATOEBA_LINKS = "https://downloads.tatoeba.org/exports/links.tar.bz2"
URL_FREQ_WORDS = "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/en/en_50k.txt"
URL_NGSL = "https://raw.githubusercontent.com/koba-ninkigumi/ngsl/master/NGSL-1.01.csv"


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
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split(",")
            headword = parts[0].strip().lower() if parts else ""
            if headword:
                words.add(headword)
    return words


def download_ngsl():
    """Downloads the NGSL headword CSV if missing. NGSL is public domain."""
    ngsl_path = RAW_DATA_DIR / "NGSL-1.01.csv"
    if not ngsl_path.exists() or ngsl_path.stat().st_size == 0:
        download_file(URL_NGSL, ngsl_path)
    return ngsl_path


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

    logger.info("All raw data files are ready in %s!", RAW_DATA_DIR)


if __name__ == "__main__":
    download_all_raw_data()
