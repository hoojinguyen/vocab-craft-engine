"""
Sample Data Generator for English Dataset System Engine.
Creates small sample raw files in data/raw/ for instant pipeline testing.
"""

import json
import csv
from pathlib import Path
from config.settings import RAW_DATA_DIR, KAIKKI_JSON_PATH, TATOEBA_SENTENCES_PATH, TATOEBA_LINKS_PATH, SUBTLEX_FREQ_PATH


def generate_sample_data():
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Sample Kaikki JSON Dump
    kaikki_samples = [
        {
            "word": "abandon",
            "pos": "verb",
            "sounds": [{"ipa": "əˈbæn.dən", "tags": ["US"]}],
            "senses": [{"glosses": ["To leave behind or give up entirely."], "examples": [{"text": "They abandoned the old house."}]}]
        },
        {
            "word": "ability",
            "pos": "noun",
            "sounds": [{"ipa": "əˈbɪl.ə.ti", "tags": ["US"]}],
            "senses": [{"glosses": ["The quality or state of being able."], "examples": [{"text": "She has the ability to learn fast."}]}]
        },
        {
            "word": "coffee",
            "pos": "noun",
            "sounds": [{"ipa": "ˈkɑː.fi", "tags": ["US"]}],
            "senses": [{"glosses": ["A hot drink made from roasted coffee beans."], "examples": [{"text": "I drink hot coffee every morning."}]}]
        },
        {
            "word": "run",
            "pos": "verb",
            "sounds": [{"ipa": "rʌn", "tags": ["US"]}],
            "senses": [{"glosses": ["To move fast on foot."], "examples": [{"text": "He runs five miles every day."}]}]
        }
    ]

    with open(KAIKKI_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(kaikki_samples, f, ensure_ascii=False, indent=2)

    # 2. Sample Tatoeba Sentences & Links
    with open(TATOEBA_SENTENCES_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow([1, "eng", "They abandoned the old house."])
        writer.writerow([2, "vie", "Họ đã bỏ lại ngôi nhà cũ."])
        writer.writerow([3, "eng", "She has the ability to learn fast."])
        writer.writerow([4, "vie", "Cô ấy có khả năng học rất nhanh."])
        writer.writerow([5, "eng", "I drink hot coffee every morning."])
        writer.writerow([6, "vie", "Tôi uống cà phê nóng mỗi sáng."])
        writer.writerow([7, "eng", "He runs five miles every day."])
        writer.writerow([8, "vie", "Anh ấy chạy 5 dặm mỗi ngày."])

    with open(TATOEBA_LINKS_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow([1, 2])
        writer.writerow([3, 4])
        writer.writerow([5, 6])
        writer.writerow([7, 8])

    # 3. Sample SUBTLEX Frequency Data
    with open(SUBTLEX_FREQ_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Word", "FREQcount", "SUBTLWF", "Lg10WF", "SUBTLKW", "Lg10KW"])
        writer.writerow(["run", "50000", "125.4", "4.7", "1000", "3.0"])
        writer.writerow(["coffee", "20000", "50.2", "4.3", "500", "2.7"])
        writer.writerow(["ability", "8000", "20.1", "3.9", "200", "2.3"])
        writer.writerow(["abandon", "2000", "5.0", "3.3", "50", "1.7"])

    print("✅ Sample raw data files successfully created in data/raw/")


if __name__ == "__main__":
    generate_sample_data()
