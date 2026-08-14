# Spec Design: TUI Dashboard & Live DAG Pipeline Monitor (Phase 2)

## 1. Mục tiêu (Goals)
Nâng cấp toàn diện giao diện dòng lệnh tương tác (Terminal UI - TUI) của VocabCraft Engine Pipeline V2 theo đúng bản thiết kế kiến trúc chuẩn (Spec Section 8).

Dashboard mới sẽ cung cấp khả năng quan sát (observability), điều khiển tương tác và giám sát luồng dữ liệu thời gian thực theo mô hình DAG:
1. **DAG Visualizer (ASCII Tree)**: Trực quan hóa cây quan hệ phụ thuộc giữa 15 bước qua 5 Levels thực thi, trạng thái đổi màu realtime.
2. **StepTable với Inline Progress Bar & ETA**: Hiển thị bảng tiến độ chi tiết từng bước, thanh tiến độ đồ họa `██████▒▒▒▒ 60%`, thời gian ước lượng hoàn thành (ETA).
3. **StepDetail Inspector (Interactive)**: Khi dùng phím mũi tên hoặc click chuột chọn 1 bước, hiển thị chi tiết: bảng phụ thuộc, bảng output, hash input, số bản ghi/batch, checkpoint và chi tiết traceback lỗi nếu fail.
4. **System & Translation Telemetry Panel**: Giám sát CPU/RAM qua `psutil`, dung lượng DuckDB staging, tốc độ xử lý (items/sec) và tỷ lệ dịch thuật (DuckDB Cache Hit / Argos Offline / Google Fallback).
5. **ProgressReporter Protocol**: Cung cấp giao thức streaming progress từ trong ruột các Step (Kaikki 3GB, Tatoeba 2M câu, OPUS 500K câu, Translation batch) lên UI theo thời gian thực mà không làm nghẽn Event Loop.

---

## 2. Bố cục giao diện TUI (Layout Grid)

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  VOCAB CRAFT ENGINE — PIPELINE MONITOR V2                         15:45:10 [RUNNING]  │
│  Elapsed: 00:04:12 | Workers: 4 | Active Level: 2/5 (4 steps running concurrently)     │
├────────────────────────────┬───────────────────────────────────────────────────────────┤
│  DAG GRAPH VIEW            │  STEP EXECUTION TABLE                                     │
│                            │  #  │ Step              │ Status  │ Progress   │ Time │ ETA│
│  Level 1:                  │  1  │ schema_init       │ ✔ DONE  │ [████████] │ 0.0s │ -  │
│    ✔ schema_init           │  2  │ ingest_kaikki     │ ● RUN   │ [████▒▒▒▒] │ 12s  │ 15s│
│  Level 2 (Parallel):       │  3  │ ingest_tatoeba    │ ✔ DONE  │ [████████] │ 18s  │ -  │
│    ● ingest_kaikki         │  4  │ ingest_opus       │ ● RUN   │ [██████▒▒] │ 45s  │ 20s│
│    ✔ ingest_tatoeba        │  5  │ ingest_wordnet    │ ● RUN   │ [██▒▒▒▒▒▒] │ 25s  │ 40s│
│    ● ingest_opus           │  ...                                                      │
│    ● ingest_wordnet        │                                                           │
│  Level 3 (Transform):      ├───────────────────────────────────────────────────────────┤
│    ○ transform_linking     │  SELECTED STEP DETAIL (ingest_kaikki)                     │
│    ○ transform_phrases     │  Type: CPU | Depends on: schema_init | Produces: words, def│
│    ○ transform_relations   │  Rows: 145,230 | Batch: #8 | Source Hash: 7a9f...         │
│  Level 4 (Enrichment):     │  Last Checkpoint: 100,000 rows | Errors: 0                │
│    ○ enrich_translation    ├───────────────────────────────────────────────────────────┤
│    ○ enrich_reflex         │  LIVE LOG STREAM                                          │
│    ○ enrich_scenarios      │  15:45:08 [INFO] [ingest_opus] Ingested 150,000 sentences │
│  Level 5 (Export):         │  15:45:09 [INFO] [ingest_kaikki] Batch #8 written to DB   │
│    ○ export_sqlite / core  │  15:45:10 [INFO] [ingest_wordnet] Synset processing 35%   │
├────────────────────────────┴───────────────────────────────────────────────────────────┤
│  SYSTEM TELEMETRY: CPU: 42.5% | RAM: 320 MB | DB Size: 48.2 MB | Speed: 12,450 rows/s  │
│  TRANSLATION ENGINE: Cache Hits: 85.2% | Argos (Offline): 14.1% | Google (Fallback): 0.7% │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Thiết kế chi tiết các Components

### 3.1 `DAGPanel` (Widget bên trái)
* Tự động sinh cây phân cấp trực tiếp từ `DAG.get_execution_levels()`.
* Cập nhật màu sắc & biểu tượng theo trạng thái của từng node:
  * `○ PENDING`: Màu xám mờ (`dim`).
  * `● RUNNING`: Màu cyan nhấp nháy hoặc nổi bật (`bold cyan`).
  * `✔ SUCCESS`: Màu xanh lá (`bold green`).
  * `✖ FAILED`: Màu đỏ (`bold red`).
  * `⊘ SKIPPED`: Màu vàng nhạt (`dim yellow`).
  * `◌ RETRYING`: Màu cam/vàng cảnh báo (`yellow`).

### 3.2 `StepTable` & Inline Progress Bars
* Sử dụng Textual `DataTable` tích hợp cột render tiến độ trực quan:
  * Công thức thanh tiến độ ASCII: `[bold cyan]██████[/bold cyan][dim]▒▒▒▒[/dim] 60%`.
  * Tính toán ETA động: `(elapsed_step / items_so_far) * (total_items - items_so_far)`.
* Cho phép người dùng di chuyển con trỏ (highlight row) để xem chi tiết bước đang chọn.

### 3.3 `StepDetailWidget` (Bảng thông tin chi tiết bước được chọn)
* Lắng nghe sự kiện `DataTable.RowHighlighted` hoặc `DataTable.RowSelected`.
* Hiển thị dạng thẻ 2 cột:
  * Cột 1: Thông tin cấu hình (`Execution Type`, `Depends On`, `Produces`, `Optional`).
  * Cột 2: Thông số runtime (`Rows Processed`, `Current Batch`, `Source File Hash`, `Retry Count`, `Execution Time`, `Error Traceback`).

### 3.4 `TelemetryPanel` & `TranslationStatsWidget`
* Tích hợp lấy mẫu chu kỳ 1.0 giây qua `psutil.Process()`.
* Thống kê kích thước file DuckDB (`staging.duckdb`).
* Truy vấn DuckDB internal table `_translation_cache` theo chu kỳ để tính % tỷ lệ:
  * `Cache Hit Ratio`
  * `Argos Offline vs Google API ratio`

### 3.5 `ProgressReporter` Protocol trong `PipelineContext`
* Cung cấp interface chuẩn cho các Step:
```python
class StepProgress:
    def __init__(self, step_name: str, total: int, reporter: ProgressReporter):
        self.step_name = step_name
        self.total = total
        self.current = 0
        
    def advance(self, count: int = 1):
        self.current += count
        self.reporter.emit_progress(self.step_name, self.current, self.total)

    def track_batch(self, count: int):
        class BatchContext:
            def __enter__(_self): pass
            def __exit__(_self, *args): self.advance(count)
        return BatchContext()
```
* Trong `BaseStep` hoặc Ingestor:
```python
progress = ctx.create_progress(self.name, total=estimated_total)
for batch in self.stream():
    with progress.track_batch(len(batch)):
        process(batch)
```
* Bắn event an toàn sang Textual thread qua `app.call_from_thread()` với throttle 100ms để tránh giật lag UI.

---

## 4. Cấu trúc Module cập nhật

```
src/pipeline/monitor/
├── __init__.py
├── dashboard.py           # Textual App chính (PipelineDashboardApp)
├── widgets/
│   ├── __init__.py
│   ├── header.py          # HeaderWidget
│   ├── dag_panel.py       # DAGPanel (ASCII tree visualization)
│   ├── step_table.py      # StepTable với inline progress bars
│   ├── step_detail.py     # StepDetail inspector
│   ├── telemetry.py       # SystemPanel & TranslationStatsWidget
│   └── log_stream.py      # RichLog stream widget
├── progress.py            # ProgressReporter & StepProgress classes
├── run_logger.py          # Structured JSON & File logger
└── metrics.py             # System telemetry collector
```

---

## 5. Kế hoạch kiểm thử & Tiêu chí nghiệm thu (Acceptance Criteria)

1. **Khả năng hiển thị (Visual Inspection)**:
   * Chạy `make run-tui` hiển thị đầy đủ bố cục 2 cột (Cây DAG bên trái, Step Table + Detail + Log bên phải, Telemetry ở footer).
2. **Tính phản hồi realtime**:
   * Khi `ingest_kaikki`, `ingest_opus` xử lý các batch 20k rows, thanh progress bar tăng dần mượt mà kèm ETA chính xác.
   * Khi chuyển qua các Level tiếp theo, cây DAG đổi màu từ pending -> running -> success.
3. **Tương tác**:
   * Bấm phím `Up`/`Down` hoặc click chuột vào bảng StepTable, panel `StepDetail` cập nhật ngay thông tin của bước đó.
   * Bấm `q` thoát an toàn, bấm `p` tạm dừng/tiếp tục.
4. **Không crash / Không leak**:
   * Không bị conflict log giữa console stdout và TUI.
   * Mọi unit test trong `tests/` tiếp tục pass 100%.
