# English Dataset System Engine

Hệ thống tự động thu thập, phân tích NLP, gán nhãn độ khó CEFR, tạo âm thanh song song và đóng gói cơ sở dữ liệu tiếng Anh (Từ vựng, Collocations, Mẫu câu, Kịch bản hội thoại rẽ nhánh, Bài tập phản xạ) dưới dạng file **SQLite DB (`english_dataset.db`)** sẵn sàng tích hợp cho các ứng dụng di động (iOS, Android, Flutter, React Native).

## 🚀 Cấu Trúc Dự Án

```
EnglishDataset/
├── config/                  # Cấu hình dự án (settings.py)
├── data/                    # Thư mục chứa dữ liệu thô, nén và DB xuất bản
│   ├── raw/                 # File Kaikki JSON, Tatoeba CSV, OPUS Subtitles
│   ├── processed/           # Staging DuckDB
│   ├── audio/               # File âm thanh MP3 (1.0x & 1.2x)
│   └── output/              # File english_dataset.db cuối cùng
├── docs/                    # Tài liệu kiến trúc & Hướng dẫn
│   ├── dataset_system_architecture.md
│   ├── execution_plan.md
│   ├── mobile_integration_guide.md
│   └── setup_guide.md
├── scripts/                 # Scripts tiện ích & Tải dữ liệu
├── src/                     # Mã nguồn chính
│   ├── ingestion/           # Parsers (Kaikki, Tatoeba, OPUS)
│   ├── nlp/                 # Lemmatizer, CEFR, Collocations, Reflex Engine
│   ├── media/               # Edge-TTS Audio Generator & IPA Mapper
│   ├── db/                  # Connection & Transaction Manager
│   └── export/              # Mobile SQLite Exporter
├── tests/                   # Pytest Automated Test Suite
├── Makefile                 # Automation Makefile script
├── main.py                  # Pipeline Runner CLI
├── pyproject.toml           # Quản lý dependencies
└── README.md
```

## 🛠️ Hướng Dẫn Sử Dụng Nhanh (Lệnh Makefile)

```bash
# 1. Khởi tạo môi trường ảo & cài đặt thư viện tự động
make setup

# 2. Tải toàn bộ dữ liệu thô (Kaikki Wiktionary & Tatoeba)
make download-data

# 3. Chạy toàn bộ pipeline ETL & tạo file english_dataset.db (có log tiến độ)
make run

# 4. Chạy kiểm thử tự động toàn hệ thống
make test
```

Xem hướng dẫn chi tiết tại: 📄 **[docs/setup_guide.md](docs/setup_guide.md)**
