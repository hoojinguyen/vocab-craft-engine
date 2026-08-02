# Multi-Word Expressions (Idioms, Phrasal Verbs, Proverbs) — Design Spec

- **Ngày:** 2026-08-03
- **Sub-project:** A trong lộ trình "Độ sâu nội dung dữ liệu" (A: Multi-word Expressions → B: Lexical Relations & Topics → C: Vietnamese Translations)
- **Trạng thái:** Đã duyệt thiết kế, chờ phê duyệt spec trước khi lập kế hoạch triển khai

## 1. Mục tiêu

Bổ sung idioms, phrasal verbs, proverbs và fixed expressions vào dataset engine. Hiện tại `kaikki_parser.py:67` lọc bỏ toàn bộ entries đa từ (`if " " in word: return None`) — dữ liệu này đã tồn tại sẵn trong Kaikki dump 3.18GB nhưng đang bị vứt bỏ. Sub-project này khai thác lại nguồn dữ liệu đó để làm giàu `english_dataset.db` cho app học tiếng Anh.

## 2. Phạm vi

**Bao gồm:**
- Cụm từ với pos ∈ {`idiom`, `phrasal verb`, `proverb`, `phrase`} trong Kaikki
- Chấm CEFR heuristic theo từ thành phần
- Câu ví dụ từ Tatoeba (substring match)
- TTS audio 1.0x/1.2x cho tất cả cụm
- Bản dịch tiếng Việt (từ Kaikki translations, fallback Translator hiện có)

**Không bao gồm:**
- Compound nouns thông dụng, proper nouns, tên riêng
- Synonyms/antonyms, word families, topics (sub-project B)
- Nâng cấp chất lượng dịch Việt (sub-project C)
- LLM/API bên ngoài cho chấm CEFR

## 3. Kiến trúc

Chọn **Phương án 1 — module mới tách biệt** (không đụng code đang chạy, test độc lập).

```
src/
├── ingestion/
│   └── phrase_parser.py          # MỚI — stream Kaikki lần 2, chỉ giữ multi-word entries
├── nlp/
│   ├── phrase_grader.py          # MỚI — CEFR theo thành phần (dùng lại CEFRGrader)
│   └── phrase_example_matcher.py # MỚI — nối câu Tatoeba chứa cụm từ
├── db/
│   └── staging_db.py             # SỬA — thêm bảng phrases, phrase_sentences + index
├── media/
│   └── audio_generator.py        # SỬA NHẸ — hàm generate cho phrase text
└── export/
    └── sqlite_exporter.py        # SỬA — export 2 bảng mới + audio_path
```

**main.py:** thêm Step mới (Phrases) sau Step 4 Media, có checkpointing `phrase_processed` — chạy lại không phải scan lại Kaikki.

Nguyên tắc module hóa: parser chỉ parse, grader chỉ chấm, matcher chỉ nối câu. Giao tiếp qua dict và DB schema, không phụ thuộc trực tiếp lẫn nhau.

### 3.1 PhraseParser (`src/ingestion/phrase_parser.py`)

Stream Kaikki dump lần 2 (dùng lại pattern ijson/JSONL của KaikkiParser), chỉ giữ entries:
- Có khoảng trắng trong `word` (multi-word)
- pos ∈ {`idiom`, `phrasal verb`, `proverb`, `phrase`}
- Từ 2–6 từ (trừ proverbs có thể dài hơn)

Trích xuất: `lemma`, `phrase_type` (ánh xạ pos), `definitions` (glosses đầu tiên), `vi_translations` (section translations code=vi), `ipa`.

### 3.2 PhraseGrader (`src/nlp/phrase_grader.py`)

Chấm CEFR heuristic dùng lại `CEFRGrader` hiện có (SUBTLEX frequency ranks):
- Tách content words trong cụm (loại stopwords the/a/of/to...)
- `max_level` = cấp cao nhất của từ thành phần
- `avg_score` = trung bình log10(rank) — khớp với logic `grade_sentence`
- `cefr_level` từ bảng ngưỡng hiện có (A1–C2)
- `difficulty_score` 1.0–6.0

Nhất quán với `CEFRGrader.grade_sentence` cho cùng chuỗi text.

### 3.3 PhraseExampleMatcher (`src/nlp/phrase_example_matcher.py`)

- Đọc câu Tatoeba đã ingest (bảng `sentences`)
- Substring match (normalize: lowercase, trim dấu câu)
- Boundary check: cụm phải đứng giữa khoảng trắng/dấu câu hai đầu (loại "give upward" khi match "give up")
- Ưu tiên câu CEFR thấp (A1 → C2)
- Cap 5 câu/cụm; thiếu thì giữ số có được

### 3.4 AudioGenerator (sửa nhẹ)

Tái sử dụng hàm TTS hiện có, sinh `phrase_{id}_std.mp3` (1.0x) và `phrase_{id}_fast.mp3` (1.2x) cho từng cụm (đặt tên theo phrase id, tránh trùng tên với audio câu `sent_*`).

### 3.5 SQLiteExporter (sửa)

Export 2 bảng mới cùng transaction với các bảng hiện có — 1 bảng fail thì rollback toàn bộ.

## 4. Luồng dữ liệu

```
Kaikki dump (scan 2) → PhraseParser → phrases (staging)
                                        ↓
           CEFRGrader + PhraseGrader → cefr_level, difficulty_score
                                        ↓
PhraseExampleMatcher ← Tatoeba sentences → phrase_sentences
                                        ↓
           AudioGenerator → MP3 1.0x/1.2x → audio_path
                                        ↓
           SQLiteExporter → english_dataset.db
```

## 5. Schema

### Bảng `phrases`

| Cột | Kiểu | Ghi chú |
|---|---|---|
| id | INTEGER PK | |
| phrase | TEXT NOT NULL | "break a leg" |
| phrase_type | TEXT | idiom / phrasal_verb / proverb / phrase |
| pos | TEXT | pos gốc từ Kaikki |
| cefr_level | TEXT | A1–C2 |
| difficulty_score | REAL | 1.0–6.0 |
| definition_en | TEXT | gloss đầu tiên |
| definition_vi | TEXT | Kaikki translations, fallback Translator |
| ipa | TEXT | nếu có |
| audio_std | TEXT | path MP3 1.0x |
| audio_fast | TEXT | path MP3 1.2x |
| audio_status | TEXT | ok / failed (mặc định ok; failed nếu TTS không tạo được) |

### Bảng `phrase_sentences`

| Cột | Kiểu | Ghi chú |
|---|---|---|
| phrase_id | INTEGER FK | → phrases.id |
| sentence_id | INTEGER FK | → sentences.id |
| rank | INTEGER | ưu tiên câu dễ trước |

### Index

`phrases(cefr_level)`, `phrases(phrase_type)`, `phrase_sentences(phrase_id)`, `phrase_sentences(sentence_id)`.

## 6. Lọc chất lượng

- Chuẩn hóa phrase: lowercase, trim dấu câu, collapse khoảng trắng
- Bỏ cụm >6 từ (trừ proverbs)
- Bỏ cụm chứa ký tự lạ (số, ký tự đặc biệt không phải chữ/dấu câu hợp lệ, hyphens chấp nhận cho compound như "well-known")
- Dedupe case/space-insensitive
- Bỏ cụm không có definition

## 7. Xử lý lỗi & Edge cases

| Tình huống | Xử lý |
|---|---|
| Crash giữa chừng | Checkpoint `phrase_processed` (last phrase id), resume từ cụm kế |
| 1 entry hỏng | Bỏ qua, log warning, tiếp tục — không chết pipeline |
| Tatoeba không có câu | Không tạo row, không bù |
| False positive match | Boundary check hai đầu cụm |
| Edge-TTS fail | Retry 2 lần → `audio_status='failed'`, export vẫn OK |
| Translator fail | Giữ definition_en làm fallback |
| Exporter fail | Rollback toàn bộ transaction |

## 8. Kiểm thử

- `tests/test_phrase_parser.py` — fixture JSON nhỏ: giữ đúng pos, loại single-word/proper noun/>6 từ, extract đúng definition/vi/ipa
- `tests/test_phrase_grader.py` — "break a leg" dễ hơn "pull the wool over someone's eyes"; nhất quán với `grade_sentence`
- `tests/test_phrase_example_matcher.py` — substring match, boundary check, cap 5, ưu tiên câu dễ, không match → không row
- `tests/test_staging_db.py` (mở rộng) — tạo bảng, index, FK constraint
- `tests/test_export.py` (mở rộng) — export đúng 2 bảng, rollback khi fail

Tiêu chí hoàn thành: `make test` xanh 100%.

## 9. Tiêu chí thành công (Success criteria)

1. `make run` hoàn tất step Phrases, tạo bảng `phrases` + `phrase_sentences` trong `english_dataset.db`
2. Dataset chứa hàng nghìn idioms/phrasal verbs/proverbs có CEFR + câu ví dụ + audio
3. `make test` 100% pass
4. Checkpointing hoạt động: chạy lại không scan lại Kaikki
