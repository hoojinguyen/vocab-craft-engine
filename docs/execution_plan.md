# Kế Hoạch Triển Khai Chi Tiết Từng Giai Đoạn (Detailed Phase-by-Phase Execution Plan)

## Tổng Quan Mục Tiêu
Xây dựng một **English Dataset System Engine** hoàn chỉnh, tự động hóa từ bước thu thập dữ liệu thô (Kaikki, Tatoeba, OPUS), xử lý NLP (Lemmatization, CEFR, Collocations, Reflex Drills, Dialogue Trees), sinh âm thanh song song (Edge-TTS), cho đến đóng gói ra file **SQLite DB (`english_dataset.db`)** đạt chuẩn hiệu năng di động (< 5ms query) và hệ thống tài liệu hướng dẫn tích hợp đầy đủ.

---

## Giai Đoạn 1: Môi Trường Dự Án & Cấu Trúc Khởi Tạo (Project Setup & Tooling)

### 1.1 Khởi Tạo Cấu Trúc Thư Mục
Tạo cấu trúc dự án chuẩn Python modulize:
```
EnglishDataset/
├── config/                  # Configuration & Environment Settings
│   └── settings.py
├── data/                    # Local storage (GitIgnored)
│   ├── raw/                 # Kaikki JSON, Tatoeba CSV, OPUS
│   ├── processed/           # Intermediate DuckDB / Parquet
│   ├── audio/               # Generated MP3s (1.0x & 1.2x)
│   └── output/              # Final english_dataset.db
├── docs/                    # Architecture & Guides
│   ├── dataset_system_architecture.md
│   ├── execution_plan.md
│   └── mobile_integration_guide.md
├── src/
│   ├── ingestion/           # Parsers (Kaikki, Tatoeba, OPUS)
│   ├── nlp/                 # Lemmatizer, CEFR, Reflex & Tree Builder
│   ├── media/               # Edge-TTS & IPA Mapper
│   ├── db/                  # Database Manager & Transactions
│   └── export/              # SQLite Exporter & Indexing
├── tests/                   # Pytest Validation Suite
├── .gitignore
├── pyproject.toml
└── README.md
```

### 1.2 Cấu Hình Dependencies & Quản Lý Gói
- Tạo file `pyproject.toml` hoặc `requirements.txt`:
  - `spacy>=3.7.0` (NLP Processing)
  - `ijson>=3.2.0` (Stream parsing file JSON dung lượng lớn)
  - `duckdb>=0.9.0` (Staging DB siêu tốc)
  - `edge-tts>=6.1.0` (Neural TTS engine miễn phí)
  - `polars>=0.20.0` (Xử lý dataframe tốc độ cao)
  - `pytest>=8.0.0` & `pytest-asyncio` (Test suite)
- Cài đặt mô hình spaCy: `python -m spacy download en_core_web_sm`.

### 1.3 Thiết Lập Settings & Dynamic Configuration (`config/settings.py`)
- Định nghĩa các hằng số: `BATCH_SIZE = 1000`, `MAX_CONCURRENT_AUDIO = 5`, `TARGET_REFLEX_TIME_MS = 2500`.
- Thiết lập đường dẫn tương đối (Pathlib) độc lập với môi trường chạy.

### 1.4 Viết Khởi Tạo Docs (`README.md` & `docs/setup_guide.md`)
- Hướng dẫn clone dự án, tạo virtualenv, tải data dumps thô và chạy pipeline.

---

## Giai Đoạn 2: Xây Dựng Tầng Thu Thập & Parse Dữ Liệu Thô (Ingestion Layer)

### 2.1 Kaikki JSON Streaming Parser (`src/ingestion/kaikki_parser.py`)
- Sử dụng `ijson` để stream từng bản ghi từ `kaikki.org-dictionary-English.json`.
- Trích xuất: `word`, `pos`, `senses` (definitions & examples), `sounds` (IPA UK/US).
- Viết unit test `tests/test_kaikki_parser.py` đảm bảo parse đúng cấu trúc JSON.

### 2.2 Tatoeba Sentence Pair Parser (`src/ingestion/tatoeba_parser.py`)
- Đọc file `sentences.csv` & `links.csv`.
- Khai thác các cặp câu dịch tương ứng Anh - Việt (`text_en`, `text_vi`).
- Lọc nhiễu: Bỏ các câu có ký tự lạ, câu dài > 30 từ hoặc câu ngắn < 2 từ.

### 2.3 OPUS Subtitles Dialogue Parser (`src/ingestion/opus_parser.py`)
- Trích xuất các luồng hội thoại ngắn (2 - 10 từ) để chuẩn bị dữ liệu cho kịch bản hội thoại (`dialogue_nodes`).

### 2.4 Staging Database Manager (`src/db/staging_db.py`)
- Quản lý kết nối DuckDB/SQLite với cơ chế **Transaction batching** (`BEGIN` ... `COMMIT` mỗi 1,000 bản ghi).
- Đảm bảo tính **Idempotent**: Dùng `INSERT OR IGNORE` trên các khóa `UNIQUE` (`words.lemma`, `sentences.text_en`).

---

## Giai Đoạn 3: Tầng NLP, Phân Cấp CEFR & Tạo Dữ Liệu Phản Xạ (NLP & Enrichment)

### 3.1 Lemmatizer & POS Tagger (`src/nlp/lemmatizer.py`)
- Sử dụng `spaCy.pipe` xử lý câu theo batch 500 câu/lần để tiết kiệm bộ nhớ.
- Tạo bảng liên kết `word_sentence_map`.

### 3.2 Tự Động Chấm Cấp Độ CEFR (`src/nlp/cefr_grader.py`)
- Nạp danh sách tần suất từ vựng (SUBTLEX-US / Oxford 3000-5000).
- Tính điểm độ khó từ vựng và tự động gán nhãn CEFR (A1, A2, B1, B2, C1, C2) cho từ vựng và câu.

### 3.3 Extractor Cụm Từ & Collocations (`src/nlp/chunk_extractor.py`)
- Trích xuất các cụm `Verb + Noun` (e.g. *take a break*) và `Verb + Preposition` (e.g. *look for*) qua spaCy Dependency Parsing.

### 3.4 Generator Bài Tập Phản Xạ (`src/nlp/reflex_builder.py`)
- Tự động quét kho câu, trích xuất đáp án chuẩn (`correct_answer`) và tạo sẵn mảng JSON 3 đáp án nhiễu (`distractors_json`) cùng cấp độ CEFR.

### 3.5 Generator Cây Hội Thoại Rẽ Nhánh (`src/nlp/scenario_builder.py`)
- Ghép nối các lượt hội thoại từ OPUS/Local LLM thành cấu trúc cây rẽ nhánh (`dialogue_trees` & `dialogue_nodes`).

---

## Giai Đoạn 4: Tầng Âm Thanh & Xử Lý Media (Media Pipeline)

### 4.1 Phonetic & IPA Mapper (`src/media/ipa_mapper.py`)
- Gán phiên âm IPA từ Kaikki. Dùng `g2p_en` làm fallback cho các từ out-of-vocabulary.

### 4.2 Batch Audio Generator (`src/media/audio_generator.py`)
- Sử dụng `edge-tts` với `asyncio.Semaphore(5)` để tạo file `.mp3` ở 2 tốc độ:
  - `Standard (1.0x)` cho học từ vựng/câu ví dụ.
  - `Fast Reflex (1.2x)` cho bài tập phản xạ.
- Tích hợp cơ chế **Exponential Backoff Retry** (3 lần thử lại nếu gặp lỗi kết nối).

---

## Giai Đoạn 5: Đóng Gói SQLite, Kiểm Thử & Docs Tích Hợp (Export & Integration Docs)

### 5.1 Mobile SQLite Exporter (`src/export/sqlite_exporter.py`)
- Export dữ liệu sang file `english_dataset.db`.
- Tối ưu hóa SQLite PRAGMAs (`journal_mode = WAL`, `synchronous = NORMAL`).
- Tạo đầy đủ các Composite Indexes (`idx_words_lemma`, `idx_reflex_cefr_type`, `idx_nodes_tree_parent`).

### 5.2 Automated Validation Suite (`tests/`)
- `tests/test_schema.py`: Kiểm tra tính toàn vẹn khóa ngoại (`PRAGMA foreign_key_check`).
- `tests/test_performance.py`: Benchmark tốc độ truy vấn bài tập phản xạ (< 5ms).

### 5.3 Tài Liệu Hướng Dẫn Tích Hợp Mobile (`docs/mobile_integration_guide.md`)
- Hướng dẫn nhúng file `english_dataset.db` vào iOS (SwiftData/FMDB), Android (Room), React Native, Flutter kèm các đoạn code SQL mẫu.
