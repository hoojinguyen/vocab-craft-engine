# Lexical Relations & Topics (Synonyms, Antonyms, Hypernyms, Hyponyms, Topics) — Design Spec

- **Ngày:** 2026-08-03
- **Sub-project:** B trong lộ trình "Độ sâu nội dung dữ liệu" (A: Multi-word Expressions ✅ → B: Lexical Relations & Topics → C: Vietnamese Translations)
- **Trạng thái:** Đã duyệt thiết kế, chờ phê duyệt spec trước khi lập kế hoạch triển khai

## 1. Mục tiêu

Bổ sung quan hệ từ vựng (synonyms, antonyms, hypernyms, hyponyms) và topics (chủ đề học tập) cho dataset engine. Kaikki dump 3.18GB **đã chứa sẵn** tất cả các trường này (`synonyms`, `antonyms`, `hypernyms`, `hyponyms` ở entry-level + sense-level, `topics` ở sense-level — đã kiểm chứng bằng sample) nhưng parser hiện tại vứt bỏ toàn bộ. Sub-project này khai thác lại nguồn dữ liệu đó để làm giàu `english_dataset.db` cho app học tiếng Anh: quiz chọn từ đồng nghĩa/trái nghĩa, browse từ theo chủ đề, học từ theo nhóm phân cấp.

## 2. Phạm vi

**Bao gồm:**
- 4 loại quan hệ từ Kaikki: `synonyms`, `antonyms`, `hypernyms`, `hyponyms` (entry-level + sense-level, dedupe)
- Topics: field `topics` của Kaikki → map qua taxonomy curated ~30 theme (fallback giữ raw normalized)
- Inverse rows cho hypernym/hyponym (dog→animal sinh animal→dog, đánh dấu `inverted=1`)
- Target: TEXT + nullable FK → `words.id` (multi-word targets giữ text, không link)
- Chỉ áp dụng cho từ đơn trong bảng `words`

**Không bao gồm:**
- Meronyms/holonyms/coordinate_terms/derived/related (niche, noise cao)
- Audio, dịch Việt, CEFR cho relations (target đã có sẵn trong bảng `words`)
- Inverse cho synonym/antonym (dữ liệu Kaikki đã đối xứng tự nhiên; inverse sẽ nhân đôi noise Thesaurus)
- Topics cho phrases (giữ scope; làm sau nếu cần)
- Nguồn ngoài (WordNet/OEWN) — Kaikki đã đủ

## 3. Kiến trúc

Chọn **Phương án 1 — mirror sub-project A** (module mới tách biệt, không đụng code đang chạy).

```
src/
├── ingestion/
│   └── relation_parser.py       # MỚI — stream Kaikki lần 3, extract relations + topics
├── nlp/
│   └── topic_mapper.py          # MỚI — taxonomy curated ~30 theme
├── db/
│   └── staging_db.py            # SỬA — thêm bảng word_relations, word_topics + index
└── export/
    └── sqlite_exporter.py       # SỬA — index 2 bảng mới
```

**main.py:** thêm Step 4H (Lexical Relations & Topics) sau Step 4G, mirror `run_phrase_step`.

### 3.1 RelationParser (`src/ingestion/relation_parser.py`)

Stream Kaikki qua `parse_raw_items()` (pattern của PhraseParser), chỉ giữ entry từ đơn (`" " not in word`). Output mỗi entry:

```
{
  "word": "dog",
  "relations": [
    {"relation_type": "hypernym", "target": "animal", "source": "hypernyms"},
    {"relation_type": "synonym", "target": "hound", "source": "synonyms"},
  ],
  "topics": [{"topic": "Zoology", "raw": "zoology"}],
}
```

Quy tắc:
- Extract từ top-level + sense-level của entry, gộp lại (theo thứ tự xuất hiện trong dump)
- **Dedupe**: cùng (word, relation_type, target) xuất hiện nhiều sense → 1 row
- **Cap 25** targets/relation_type/word, giữ theo thứ tự xuất hiện
- Bỏ target không hợp lệ: 1 ký tự, chứa số, chứa ký tự lạ (tái dùng `CLEAN_CHARS_PATTERN` của PhraseParser)
- `target_text` chuẩn hóa lowercase trước khi đưa vào batch (chống trùng case: "Dog" và "dog")
- Topics extract **độc lập** với relations: entry không còn relation nào sau cap vẫn yield topics
- Topics map qua `TopicMapper` ngay tại parser (lưu cả raw lẫn theme)

### 3.2 TopicMapper (`src/nlp/topic_mapper.py`)

Module thuần, không IO. Dict ánh xạ raw Kaikki topic → theme curated (~30 themes: Technology, Health & Medicine, Business, Travel, Food & Drink, Education, Nature, Sports, Law & Government, Arts & Entertainment, Science, Home & Family, Emotions, Communication, ...).

- API: `map_topic(raw: str) -> str` — map khớp; fallback trả raw normalized (lowercase → Title Case, "natural-sciences" → "Natural-Sciences")

### 3.3 Step 4H `run_relations_step(db_manager, args)` (main.py)

Mirror `run_phrase_step`:

1. **Checkpoint**: `SELECT count(*) FROM word_relations` > 50000 AND `SELECT count(*) FROM word_topics` > 1000 → skip (trừ `--force-reset`), log "CHECKPOINT DETECTED"
2. Stream Kaikki → `RelationParser` → accumulate dicts → `insert_word_relations_batch` (1000 rows/batch)
3. **Link targets**: `SELECT id, lemma FROM words` → build lemma→id map → gán `target_word_id` khi target là từ đơn khớp lemma
4. **Inverse pass**: mỗi hypernym row (word_id=A, target=B) → sinh row (word_id=B, target=A, relation_type=hyponym, inverted=1, source giữ nguyên section gốc); batch 5000 rows; UNIQUE constraint + OR IGNORE chống trùng row tự nhiên
5. `insert_word_topics_batch` (1000 rows/batch)
6. Return `{"relations": n, "links": n, "topics": n}`

## 4. Schema

### Bảng `word_relations`

| Cột | Kiểu | Ghi chú |
|---|---|---|
| id | INTEGER PK | |
| word_id | INTEGER FK NOT NULL | → words.id, từ chủ (owner) |
| relation_type | TEXT NOT NULL | synonym / antonym / hypernym / hyponym |
| target_text | TEXT NOT NULL | "animal" hoặc "give up the ghost" |
| target_word_id | INTEGER FK NULL | → words.id khi target là từ đơn có trong DB |
| inverted | INTEGER NOT NULL DEFAULT 0 | 0 = chiều tự nhiên; 1 = inverse sinh ra |
| source | TEXT | tên section nguồn (synonyms/hypernyms/...) |

**Index:**
- UNIQUE `(word_id, relation_type, target_text)` — idempotent khi chạy lại
- `(target_word_id)` — query ngược (từ nào trỏ tới word này)

### Bảng `word_topics`

| Cột | Kiểu | Ghi chú |
|---|---|---|
| word_id | INTEGER FK NOT NULL | → words.id |
| topic | TEXT NOT NULL | theme curated: "Technology", "Travel"... |
| raw_topic | TEXT | topic gốc từ Kaikki ("computing") |

**Index:**
- UNIQUE `(word_id, topic)` — chống trùng
- `(topic)` — browse theo theme

Không tạo bảng `topics` riêng (YAGNI — app JOIN từ `word_topics` + DISTINCT).

## 5. Luồng dữ liệu

```
Kaikki dump (scan 3) → RelationParser → word_relations (staging)
                        ├─ TopicMapper → word_topics
                        ├─ link words.lemma → target_word_id
                        └─ inverse pass → hyponym rows (inverted=1)
                                              ↓
                        SQLiteExporter (index) → english_dataset.db
```

## 6. Lọc chất lượng

- Cap 25 targets/relation_type/word (chống noise Thesaurus — "dictionary" có 2000+ synonyms)
- Bỏ target 1 ký tự, chứa số, ký tự lạ
- Bỏ entry không có relation nào sau cap
- Dedupe case-insensitive target (dog ↔ Dog về 1 row)
- Raw topic không map được → fallback giữ raw normalized

## 7. Xử lý lỗi & Edge cases

| Tình huống | Xử lý |
|---|---|
| Crash giữa chừng | Checkpoint count-based (như 4G); chạy lại idempotent nhờ UNIQUE + OR IGNORE |
| 1 entry hỏng (sai shape) | Bỏ qua, log warning, tiếp tục |
| Target không có trong `words` | Giữ `target_text`, `target_word_id = NULL` |
| Inverse trùng row tự nhiên | UNIQUE constraint → OR IGNORE bỏ qua |
| Raw topic không map được | Fallback: raw normalized (lowercase → Title Case) |
| Cap đạt 25 | Dừng lấy thêm target cho loại đó, tiếp tục entry khác |
| Exporter fail | Transaction rollback (cơ chế sẵn có) |

## 8. Kiểm thử

- `tests/test_topic_mapper.py` — "computing"→"Technology", fallback raw, case normalization
- `tests/test_relation_parser.py` — fixture JSON nhỏ: extract đúng 4 loại relation, dedupe giữa senses, cap 25, lọc target xấu, topics map đúng theme, bỏ entry đa từ
- `tests/test_staging_db.py` (mở rộng) — 2 bảng mới, UNIQUE constraints, FK
- `tests/test_relations_pipeline.py` — e2e: fixture 3 từ (dog/animal/quick + 1 multi-word target): relation insert, inverse row (animal→dog inverted=1), target_word_id link đúng, topics insert; checkpoint test (seed vượt ngưỡng → skip, parser không được gọi)

Tiêu chí hoàn thành: `make test` xanh 100%.

## 9. Tiêu chí thành công (Success criteria)

1. `make run` hoàn tất Step 4H, tạo `word_relations` + `word_topics` trong `english_dataset.db`
2. Dataset chứa hàng trăm nghìn relations (có inverse + link đầy đủ) và topics
3. `make test` 100% pass
4. Checkpointing hoạt động: chạy lại không re-scan Kaikki
