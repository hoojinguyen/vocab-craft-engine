# Spec Design: Translation Offline Setup, NLTK Automation & Telemetry Tracking (Phase 3)

## 1. Mục tiêu (Goals)
Hoàn thiện toàn diện hạ tầng dịch thuật offline và tự động hóa tải dữ liệu ngôn ngữ (NLTK & Argos Translate) cho VocabCraft Engine Pipeline V2:
1. **NLTK Corpus Download nội bộ**: Cố định đường dẫn tải về thư mục dự án (`data/raw/nltk_data` hoặc `.venv/nltk_data`) cho toàn bộ các gói: `wordnet`, `cmudict`, `averaged_perceptron_tagger_eng`, `omw-1.4`, `punkt_tab`.
2. **Tự động hóa Argos Offline Translation (`en_vi`)**: Cung cấp cơ chế tự động kiểm tra, tải về và cài đặt gói model ngôn ngữ offline English -> Vietnamese (`argostranslate`) trong script `download_raw_data.py`.
3. **Bộ đếm Telemetry & Quota Accounting cho `HybridTranslator`**: Theo dõi chính xác từng request dịch thuật (`Cache Hits`, `Argos Offline`, `Google Fallback`, `Validation Rejects`), ghi log tổng kết khi kết thúc step và đồng bộ lên TUI TelemetryPanel.

---

## 2. Thiết kế chi tiết các Hạng mục

### 2.1 Cải tiến NLTK Corpus Downloader trong `scripts/download_raw_data.py`
* Hàm `download_nltk_corpora()`:
  * Xác định `target_dir = NLTK_DATA_DIR` (hoặc `VENV_NLTK_DATA_DIR`).
  * Tạo thư mục đích nếu chưa có.
  * Tải đầy đủ danh sách packages:
    * `wordnet` (Lemmatization & Synsets)
    * `cmudict` (Phonetic IPA mapping)
    * `averaged_perceptron_tagger_eng` (POS Tagging)
    * `omw-1.4` (Open Multilingual WordNet)
    * `punkt_tab` (Sentence / Tokenizer tokenization)
  * Gọi `nltk.download(pkg, download_dir=str(target_dir), quiet=True)`.

### 2.2 Tự động cài đặt Argos Translate English -> Vietnamese
* Hàm `install_argos_models()` trong `scripts/download_raw_data.py`:
  * Kiểm tra xem `argostranslate` đã được cài đặt trong môi trường chưa.
  * Lấy danh sách các installed languages:
    ```python
    installed = argostranslate.translate.get_installed_languages()
    # Tìm xem đã có pair English -> Vietnamese chưa
    ```
  * Nếu chưa có:
    * Cập nhật index package: `argostranslate.package.update_package_index()`
    * Tìm package có `from_code == "en"` và `to_code == "vi"`
    * Tải và cài đặt: `argostranslate.package.install_from_path(download_path)`
  * Nếu có lỗi mạng (offline), fallback an toàn mà không làm crash script.

### 2.3 Quota Accounting & Telemetry trong `HybridTranslator`
* Tạo dataclass `TranslationStats`:
  ```python
  @dataclass
  class TranslationStats:
      cache_hits: int = 0
      argos_translated: int = 0
      google_translated: int = 0
      validation_rejected: int = 0
      total_requested: int = 0
  ```
* Trong `HybridTranslator`:
  * Tích hợp instance `self.stats = TranslationStats()`
  * Mỗi khi tra cứu cache thành công -> `stats.cache_hits += 1`
  * Mỗi khi dịch qua Argos thành công & pass validator -> `stats.argos_translated += 1`
  * Mỗi khi fallback sang Google Translate -> `stats.google_translated += 1`
  * Nếu kết quả dịch không hợp lệ (bị reject bởi `VietnameseValidator`) -> `stats.validation_rejected += 1`
  * Cung cấp method `get_summary() -> Dict[str, Any]` trả về báo cáo chi tiết.
* Trong `EnrichTranslationStep.run()`:
  * Ghi log kết quả tổng quan:
    `[INFO] Translation Complete: X defs, Y phrases | Cache Hits: A (..%) | Argos: B | Google: C | Rejects: D`
  * Truyền stats vào metadata / metrics của `StepResult`.

---

## 3. Kế hoạch kiểm thử & Tiêu chí nghiệm thu

1. **Unit Tests**:
   * Test `download_nltk_corpora()` ghi nhận đúng `download_dir`.
   * Test `install_argos_models()` xử lý an toàn khi đã có package hoặc khi offline.
   * Test `HybridTranslator.stats` đếm chính xác từng loại request (cache vs argos vs google vs reject).
2. **Integration Tests**:
   * Chạy `pytest tests/test_enrichment/test_translation.py` và toàn bộ test suite pass 100%.
   * Chạy `python scripts/download_raw_data.py` (hoặc test mock) không bị permission error.
