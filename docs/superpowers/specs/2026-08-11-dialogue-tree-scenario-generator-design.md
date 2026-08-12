# Design Spec: Automatic Dialogue Tree Scenario Generator

**Date:** 2026-08-11  
**Status:** Approved  
**Module:** `src/nlp/scenario_builder.py`, `src/db/staging_db.py`, `main.py`, `src/export/sqlite_exporter.py`  

---

## 1. Executive Summary & Goals

The Automatic Dialogue Tree Scenario Generator (`ScenarioBuilder`) constructs interactive branching situational dialogue trees (`dialogue_trees` and `dialogue_nodes`) for English learners across 25+ real-world topics (Dining, Hotels, Travel, Shopping, Airports, Job Interviews, Healthcare, Socializing). It automatically links dialogue turn text with the `sentences` corpus table to leverage CEFR grading, Vietnamese translation validation, and dual-speed Neural TTS audio synthesis. It exports an optimized mobile SQL View `v_dialogue_nodes` with sub-0.5ms node traversal latency.

---

## 2. Architecture & Scenario Registry Design

### 2.1 Scenario Builder (`src/nlp/scenario_builder.py`)
Class `ScenarioBuilder` maintains a curated catalog of 25+ structured branching scenarios categorized across CEFR `A1` to `B2` levels and 8 primary situational themes.

#### Category Themes (25+ Scenarios):
1. **Cafe & Restaurant** (Ordering food/drinks, requesting check, complaining about order)
2. **Hotel & Accommodation** (Checking in, room upgrade, reporting issues)
3. **Travel & Directions** (Asking for directions, buying train tickets, taking a taxi)
4. **Shopping & Retail** (Asking prices, trying clothes, bargaining, returning items)
5. **Airport & Customs** (Flight check-in, security screening, passport control)
6. **Job Interview & Work** (Self-introduction, discussing experience, salary negotiation)
7. **Medical & Healthcare** (Describing symptoms at doctor's, buying medicine)
8. **Socializing & Daily Life** (Weekend plans, inviting friends, making small talk)

#### Node Schema:
Each scenario tree is built as a parent-child branching graph:
```python
{
    "title": "Ordering Coffee at a Cafe",
    "topic": "Dining",
    "cefr_level": "A2",
    "nodes": [
        {"node_index": 0, "parent_index": None, "speaker_role": "A", "choice_label": None, "text_en": "Hi! What can I get started for you today?", "text_vi": "Xin chào! Bạn muốn gọi món gì hôm nay?"},
        {"node_index": 1, "parent_index": 0, "speaker_role": "B", "choice_label": "Order a Hot Latte", "text_en": "I'd like a hot latte, please.", "text_vi": "Cho tôi một ly latte nóng."},
        {"node_index": 2, "parent_index": 0, "speaker_role": "B", "choice_label": "Order an Iced Coffee", "text_en": "Just an iced Americano for me, thanks.", "text_vi": "Cho tôi một ly Americano đá, cảm ơn."},
        {"node_index": 3, "parent_index": 1, "speaker_role": "A", "choice_label": None, "text_en": "Sure thing! What size would you like?", "text_vi": "Dạ được! Bạn muốn dùng size nào?"},
        {"node_index": 4, "parent_index": 2, "speaker_role": "A", "choice_label": None, "text_en": "Got it. Would you like any sugar with that?", "text_vi": "Đã rõ. Bạn có muốn thêm đường không?"}
    ]
}
```

---

## 3. Database & Pipeline Integration

### 3.1 Database Manager Batch Helpers (`src/db/staging_db.py`)
Add batch write helpers:
- `insert_dialogue_tree_with_nodes(self, scenario: Dict[str, Any]) -> int`:
  1. Inserts tree record into `dialogue_trees(title, topic, cefr_level)`.
  2. Resolves node sentence text against `sentences` table (fetching existing `sentence_id` or inserting new `sentences` record).
  3. Maps `node_index` -> `db_node_id` and `parent_index` -> `db_parent_node_id`.
  4. Inserts nodes into `dialogue_nodes(tree_id, parent_node_id, choice_label, speaker_role, sentence_id)`.
  5. Updates `dialogue_trees.root_node_id` with root node ID (`node_index == 0`).
- `insert_dialogue_scenarios_batch(self, scenarios: List[Dict[str, Any]]) -> Tuple[int, int]`: Inserts multiple scenarios in a single atomic transaction.

### 3.2 Pipeline Step (`main.py`)
Function `run_scenario_step(db_mgr: DatabaseManager) -> Tuple[int, int]`:
1. Instantiates `ScenarioBuilder`.
2. Calls `build_all_scenarios()`.
3. Inserts all scenario trees and nodes via `insert_dialogue_scenarios_batch()`.
4. Returns `(trees_count, nodes_count)`.
5. Connected to Step 4D of `run_pipeline()`.

### 3.3 Mobile Exporter & SQL View (`src/export/sqlite_exporter.py`)
Creates SQL View `v_dialogue_nodes`:
```sql
CREATE VIEW IF NOT EXISTS v_dialogue_nodes AS
SELECT 
    dn.id AS node_id,
    dn.tree_id,
    dn.parent_node_id,
    dn.choice_label,
    dn.speaker_role,
    dn.sentence_id,
    s.text_en,
    s.text_vi,
    s.cefr_level,
    s.audio_path
FROM dialogue_nodes dn
LEFT JOIN sentences s ON dn.sentence_id = s.id;
```
Ensures index `idx_nodes_tree_parent` on `dialogue_nodes(tree_id, parent_node_id)` and adds `scenario_traversal_ms` SLA benchmark (< 0.5 ms).

---

## 4. Testing & Verification Plan

1. **Unit Tests (`tests/test_scenario_builder.py`):**
   - Verify 25+ scenarios build cleanly with valid parent-child node indices and speaker roles (`A`/`B`).
2. **Integration Tests (`tests/test_scenario_pipeline.py`):**
   - Test `run_scenario_step()` end-to-end on staging database.
   - Verify `dialogue_trees`, `dialogue_nodes`, and automatic `sentences` population.
3. **Mobile Performance Tests (`tests/test_sqlite_exporter.py`):**
   - Verify `v_dialogue_nodes` SQL View execution.
   - Assert `scenario_traversal_ms` latency < 0.5 ms.
