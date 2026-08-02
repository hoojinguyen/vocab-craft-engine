# Hướng Dẫn Cài Đặt Môi Trường & Chạy Pipeline

Tài liệu này hướng dẫn chi tiết cách thiết lập môi trường phát triển Python, tự động tải dữ liệu thô và chạy pipeline đóng gói dữ liệu cho hệ thống **English Dataset Engine**.

---

## 1. Yêu Cầu Tiền Đề (Prerequisites)

- **Python 3.11+**
- **Make** (`make`)
- **Git**

---

## 2. Thiết Lập Môi Trường Tự Động Với `make`

Mở terminal tại thư mục gốc dự án và chạy duy nhất lệnh sau để tự động khởi tạo môi trường ảo `.venv`, cài đặt thư viện, mô hình spaCy và NLTK tagger:

```bash
make setup
```

---

## 3. Tải Dữ Liệu Thô (Raw Datasets)

Để tự động tải bộ dữ liệu thô (Kaikki Wiktionary 3.18GB & Tatoeba Anh-Việt) vào thư mục `data/raw/`:

```bash
make download-data
```

---

## 4. Thực Thi Pipeline & Đóng Gói Database

Chạy toàn bộ pipeline ETL 5 bước có hiển thị progress log thời gian thực:

```bash
make run
```

*Trong quá trình chạy, hệ thống sẽ in log tiến độ chi tiết theo định dạng:*
- `[Step 1/5] Initializing SQLite Database Schema...`
- `[Step 2/5] Ingesting Kaikki Dictionary (3.18 GB dump)...`
  - `-> Processed 50,000 dictionary entries...`
  - `-> Processed 100,000 dictionary entries...`
- `[Step 3/5] Ingesting Tatoeba Parallel Sentences...`
- `[Step 4/5] Running NLP Enrichment (Collocations, Scenarios, Reflex Drills)...`
- `[Step 5/5] Packaging & Optimizing SQLite Mobile Database...`

---

## 5. Chạy Kiểm Thử Tự Động (Pytest)

```bash
make test
```
