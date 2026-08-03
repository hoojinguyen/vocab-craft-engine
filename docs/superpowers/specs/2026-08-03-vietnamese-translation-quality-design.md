# Vietnamese Translation Quality & Backfill — Design Spec

- **Ngày:** 2026-08-03
- **Sub-project:** C trong lộ trình "Độ sâu nội dung dữ liệu" (A: Multi-word Expressions → B: Lexical Relations & Topics → C: Vietnamese Translations)
- **Trạng thái:** Đã duyệt thiết kế, chờ phê duyệt spec trước khi lập kế hoạch triển khai

## 1. Mục tiêu

Đảm bảo mọi từ có thể học được (prioritized words) trong dataset đều có bản dịch tiếng Việt thật sự. Hiện tại:

- `kaikki_parser.py:149` lưu **gloss tiếng Anh làm `definition_vi`** khi không có bản dịch tự nhiên (English passthrough / data pollution).
- `Translator.translate_text` (deep_translator Google) trả về text gốc khi dịch fail — cũng tạo passthrough cho `collocations.meaning_vi` và `phrases.definition_vi`.
- Hàng nghìn definitions/collocations/phrases có `definition_vi`/`meaning_vi` bằng tiếng Anh, không phải tiếng Việt.

Sub-project này: làm sạch dữ liệu cũ, backfill ưu tiên các từ học được, và chặn passthrough từ nguồn.

## 2. Phạm vi

**Bao gồm:**
- Fix pollution tại nguồn: `kaikki_parser.py:149` bỏ fallback gloss tiếng Anh.
- Cleanup 1 lần: đặt `definition_vi`/`meaning_vi` = NULL cho các row đang chứa English passthrough (vi == en / vi == gloss).
- Step mới `run_vietnamese_step()` (4I) trong `main.py`: backfill có checkpoint, ưu tiên từ học được.
- `VietnameseTextValidator` — validation heuristic thuần logic, không network.
- Nâng cấp `Translator.translate_text` với validation + retry + ghi NULL thay vì passthrough.

**Không bao gồm:**
- LLM dịch (offline + cost).
- Multi-provider fallback mới (argos/LibreTranslate) — không thêm deps.
- Dịch toàn bộ ~1M glosses không ưu tiên (chỉ khi MT budget cho phép).
- Đụng `sentences.text_vi` từ Tatoeba (đã native, chất lượng tốt).
- Dịch gloss đầu tiên sang các ngôn ngữ khác ngoài Việt.

## 3. Kiến trúc

Chọn **Phương án Step 4I riêng** (mirror Step 4G/4H, checkpointed, test e2e) + fix pollution tại nguồn.

```
src/
├── nlp/
│   ├── vi_validator.py   # MỚI — VietnameseTextValidator: is_vietnamese(text) -> bool (pure, tested)
│   └── translator.py     # SỬA — translate_text có validation + retry, NULL thay vì passthrough
├── ingestion/
│   └── kaikki_parser.py  # SỬA NHẸ — bỏ fallback `vi_trans_str or gloss.strip()`
├── db/
│   └── staging_db.py     # SỬA — thêm phương thức đọc/update candidates ưu tiên
└── export/
    └── sqlite_exporter.py # KHÔNG đổi (schema không thay đổi)
```

**main.py:** thêm `run_vietnamese_step(db_manager, args)` — Step 4I sau block 4H, checkpoint count-based, re-run idempotent.

Nguyên tắc module hóa: `VietnameseTextValidator` thuần (không network, không phụ thuộc Translator), `Translator` dùng validator, `run_vietnamese_step` phối bản qua DB. Mỗi đơn vị test độc lập.

### 3.1 VietnameseTextValidator (`src/nlp/vi_validator.py`)

Thuần logic, không I/O, không network. Interface:

```python
class VietnameseTextValidator:
    VIETNAMESE_SPECIFIC_CHARS = set("ăâđêôơư")  # + chữ có thanh điệu
    TONE_MARKED_VOWELS = set("àáảãạèéẻẽẹìíỉĩịòóỏõọùúủũụỳýỷỹỵ")
    ENGLISH_FUNCTION_WORDS = {"the", "and", "of", "to", "with", "for", "is",
                              "are", "a", "an", "this", "that", "you", "in"}

    def is_vietnamese(self, text: str) -> bool
```

Heuristic (theo thứ tự):
1. Có ≥1 ký tự Việt đặc trưng (ăâđêôơư hoặc nguyên âm mang thanh) → **accept** (borrowed words rất hiếm trong gloss).
2. Toàn ASCII + có **≥2** English function words → **reject** (passthrough).
3. Còn lại (ngắn, mơ hồ, không dấu như "ban") → **accept** (MT fail hiếm khi trả text thuần Anh qua step 2; chữ vay "class" không có function words — giữ vì KHÔNG reject sai).

### 3.2 Translator — nâng cấp (`src/nlp/translator.py`)

- `translate_text(text)` giữ signature cũ (không vỡ callers cũ: main.py:92, main.py:446).
- Sau khi `GoogleTranslator` trả kết quả: `validator.is_vietnamese(result)` → không hợp lệ thì retry 1 lần (fresh translator), vẫn fail thì **return ""/None** (không lưu passthrough).
- Cache JSON giữ nguyên (`translation_cache.json`) — chỉ lưu bản dịch được chấp nhận; passthrough bị reject thì không ghi cache.
- Error path (network/rate limit): log warning, `return ...` — main.py quyết định NULL hoặc bỏ qua.

### 3.3 Step 4I (`run_vietnamese_step`)

**Priority order (backfill):**
1. definitions của từ có `audio_status='ok'` (word có audio → học được).
2. definitions của từ xuất hiện trong `collocations` / `phrases` / `reflex_drills` (reflex engine).
3. (Nếu MT budget còn) phần definitions còn lại.

**Luồng:**
```
1. Cleanup: UPDATE definitions/phrases SET definition_vi=NULL WHERE
   definition_vi = definition_en; UPDATE collocations
   SET meaning_vi=NULL WHERE meaning_vi = phrase.
2. Đếm candidates ưu tiên (definition_vi IS NULL, thuộc nhóm ưu tiên).
   Nếu = 0 và không force_reset → CHECKPOINT SKIP.
3. Với mỗi candidates batch (1000):
   - native vi từ Kaikki? (đã có sẵn → skip)
   - translate_text → validate → update batch (UPDATE definitions SET definition_vi)
4. Log tóm tắt: # updated, # skipped có native, # failed (NULL).
```

Không đụng `translations` từ Kaikki đã lưu trong `definition_vi` khi nó hợp lệ (native Vietnamese). Chỉ backfill các row NULL.

**Checkpoint:** count-based trên số row ưu tiên còn NULL. force_reset ép chạy lại toàn bộ.

## 4. Luồng dữ liệu

```
Kaikki dump → (definitions có native vi từ Kaikki đã có sẵn)
                                     ↓
          candidate definitions (ưu tiên)  + collocations + phrases
                                     ↓
      Translator.translate_text → VietnameseTextValidator.is_vietnamese
                                     ↓
                    accept → UPDATE DB + cache JSON
                    reject → retry 1× → NULL (không passthrough)
```

## 5. Schema

**Không đổi** (không thêm bảng/cột). Chỉ data migration (cleanup 1 lần) + update.

## 6. Lọc chất lượng

- `is_vietnamese` heuristic (mục 3.1) — bằng chương trình, không cần data ngoài.
- Không lưu passthrough: mọi giá trị vi = NULL thay vì văn bản English.
- Retry 1 lần khi reject; 429 → backoff (nghỉ giữa batch).

## 7. Xử lý lỗi & Edge cases

| Tình huống | Xử lý |
|---|---|
| Crash giữa chừng | Checkpoint count-based, resume từ candidates còn NULL; cache giữ intermediate |
| Network fail / 429 | Backoff giữa batch (sleep), retry 1×/item; item fail → NULL |
| văn bản vay mượn ("cafe", "class") | Validator không số hóa được → accept (thấp hơn mức tác động) |
| Translator trả text Anh | is_valid False → reject → NULL |
| Row đã có native vi (Kaikki) | Bỏ qua, không translate |
| Exporter không đổi | không rollback mới |

## 8. Kiểm thử

- `tests/test_vi_validator.py` — tiếng Việt có dấu/không dấu, văn bản Anh, mixed, text ngắn.
- `tests/test_nlp.py` (mở rộng) — Translator giữ passthrough reject, retry, cache không lưu passthrough.
- `tests/test_vietnamese_pipeline.py` — e2e: cleanup pollution, backfill ưu tiên, checkpoint skip, re-run idempotent, MT fake trả tiếng Anh → NULL.
- `tests/test_staging_db.py` (mở rộng, nếu add DB methods) — phương thức đọc/update candidate.

Tiêu chí: `make test` xanh 100%.

## 9. Tiêu chí thành công (Success criteria)

1. `make run` hoàn tất Step 4I: 100% definitions của prioritized words có `definition_vi` hợp lệ (native hoặc MT-validated), **0 row passthrough** còn lại.
2. Checkpoint hoạt động: chạy lại bỏ qua (count-based).
3. `make test` 100% pass.
4. Không row mới lưu English vào `definition_vi`/`meaning_vi` từ ingestion.