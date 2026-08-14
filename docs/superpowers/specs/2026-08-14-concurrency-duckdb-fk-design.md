# Spec Design: Concurrency Hardening, Thread-Safe DuckDB & Foreign Key Integrity (Group 1 P0)

## 1. Mục tiêu (Goals)
Sửa đổi triệt để các rủi ro concurrency và vi phạm Foreign Key constraints khi các Pipeline Steps chạy song song đa luồng trong VocabCraft Engine Pipeline V2:
1. **Thread-Safe DuckDB Operations (`DuckDBManager`)**: Cung cấp giao diện truy vấn đồng bộ hóa (`execute`, `fetch_all`, `fetch_one`, `with db_mgr.lock:`, `with db_mgr.connection():`), loại bỏ hoàn toàn các lời gọi truy vấn không an toàn trên DuckDB connection chia sẻ.
2. **Unique Dynamic Temp Table Registration**: Sử dụng tên định danh duy nhất (chứa thread id / uuid) khi đăng ký PyArrow table tạm thời trong DuckDB (`_tmp_arrow_{thread_id}_{nonce}`), tránh xung đột giữa các luồng chạy đồng thời.
3. **Dynamic Word ID Resolution trong `WordNetIngestor`**: Thay thế cơ chế snapshot tĩnh bằng cơ chế phân giải batch động (dynamic batch lookup / SQL join), đảm bảo `word_id` và `target_word_id` luôn chính xác 100% khi `KaikkiIngestor` và `WordNetIngestor` chèn dữ liệu song song.
4. **Foreign Key Integrity Validation**: Đảm bảo 0 bản ghi mồ côi (orphaned records) hoặc vi phạm khoá ngoại trong `definitions`, `word_relations`, `word_topics`, `word_sentences`, `phrase_sentences`.

---

## 2. Thiết kế chi tiết các Hạng mục

### 2.1 Nâng cấp `DuckDBManager` (`src/db/duckdb_manager.py`)
* **Thread Lock Context Manager**:
  * Cung cấp thuộc tính `db_mgr.lock` (sử dụng `threading.RLock()`).
  * Bổ sung helper `execute(sql: str, params: Optional[Sequence[Any]] = None) -> duckdb.DuckDBPyConnection`:
    ```python
    def execute(self, sql: str, params: Optional[Sequence[Any]] = None):
        with self._lock:
            conn = self.get_connection()
            return conn.execute(sql, params) if params is not None else conn.execute(sql)
    ```
  * Bổ sung helper `fetch_all(sql: str, params: Optional[Sequence[Any]] = None) -> List[Tuple]`:
    ```python
    def fetch_all(self, sql: str, params: Optional[Sequence[Any]] = None) -> List[Tuple]:
        with self._lock:
            conn = self.get_connection()
            res = conn.execute(sql, params) if params is not None else conn.execute(sql)
            return res.fetchall()
    ```
  * Bổ sung helper `fetch_one(sql: str, params: Optional[Sequence[Any]] = None) -> Optional[Tuple]`:
    ```python
    def fetch_one(self, sql: str, params: Optional[Sequence[Any]] = None) -> Optional[Tuple]:
        with self._lock:
            conn = self.get_connection()
            res = conn.execute(sql, params) if params is not None else conn.execute(sql)
            return res.fetchone()
    ```
* **Dynamic Table Isolation trong `insert_batch_fast` / `insert_arrow`**:
  * Tên bảng tạm PyArrow: `temp_name = f"_tmp_arrow_{threading.get_ident()}_{uuid.uuid4().hex[:8]}"`
  * Đăng ký, chèn dữ liệu `INSERT OR IGNORE`, và hủy đăng ký an toàn trong khối `try/finally` bên dưới `self._lock`.

### 2.2 Dynamic Word ID Resolution trong `WordNetIngestor` (`src/ingestion/wordnet_ingestor.py`)
* `WordNetIngestor.ingest()`:
  * **Bước 1: Chèn từ vựng (Words)**:
    * Thu thập danh sách `(lemma, pos)` từ các synsets.
    * Chèn vào bảng `words` thông qua `db_mgr.insert_batch_fast("words", words_batch)`.
  * **Bước 2: Phân giải ID động cho Definitions & Relations**:
    * Khi chuẩn bị chèn `definitions` và `word_relations`, gom nhóm theo từng batch.
    * Đối với mỗi batch, trích xuất tập hợp các `(lemma, pos)` cần tra cứu.
    * Thực hiện dynamic query:
      ```sql
      SELECT lemma, pos, id FROM words WHERE (lemma, pos) IN (...)
      ```
      hoặc tạo bảng tạm danh sách lemma/pos và `JOIN words` để lấy `word_id` chính xác nhất tại thời điểm chèn.
    * Chỉ chèn `definitions` khi `word_id` tồn tại hợp lệ trong database.
    * Đối với `word_relations`, chỉ chèn khi `word_id` hợp lệ; `target_word_id` nếu tìm thấy sẽ gán ID, nếu chưa có trong database sẽ để `NULL` và để bước `RelationBuilder` ở Level 2 tự động phân giải (resolve).

### 2.3 Đồng bộ hóa các Transformer & Ingestor còn lại
* Các modules: `SentenceLinker`, `PhraseExtractor`, `TopicMapper`, `RelationBuilder`, `ReflexBuilder`, `ScenarioBuilder`:
  * Sử dụng `db_mgr.execute(...)`, `db_mgr.fetch_all(...)`, `db_mgr.fetch_one(...)` hoặc bọc các khối multi-statement trong `with db_mgr.lock:`.
  * Thay thế tên bảng tạm cố định (ví dụ `_tmp_resolved_targets`, `_tmp_inv_candidates`) bằng tên có gắn `threading.get_ident()`.

---

## 3. Kế hoạch kiểm thử & Tiêu chí nghiệm thu

1. **Unit & Stress Tests**:
   * `test_duckdb_manager_concurrency.py`: 10 luồng cùng lúc thực hiện đọc/ghi/đăng ký bảng tạm PyArrow vào DuckDB, kiểm tra không bị lỗi và không xảy ra race condition.
   * `test_ingestor_concurrency_fk.py`: Khởi chạy `KaikkiIngestor` và `WordNetIngestor` đồng thời trên 2 luồng riêng biệt với tập dữ liệu giả lập lớn, kiểm tra:
     * 0 lỗi ngoại lệ (No exceptions).
     * 0 lỗi Foreign Key constraint violation.
     * Toàn bộ `definitions` đều có `word_id` trỏ đến `words(id)` hợp lệ:
       `SELECT count(*) FROM definitions WHERE word_id NOT IN (SELECT id FROM words) == 0`.
     * Toàn bộ `word_relations` đều có `word_id` trỏ đến `words(id)` hợp lệ:
       `SELECT count(*) FROM word_relations WHERE word_id NOT IN (SELECT id FROM words) == 0`.
2. **Toàn bộ Test Suite**:
   * Đảm bảo 100% bài test hiện có (276 tests) tiếp tục pass và các test mới đều pass.
