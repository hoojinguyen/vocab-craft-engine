# Automatic Dialogue Tree Scenario Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated Dialogue Tree Scenario Generator (`ScenarioBuilder`) with 25+ curated situational scenario trees across 8 themes (A1 to B2), auto-linking turn sentences into `sentences`, storing trees and nodes into `dialogue_trees` and `dialogue_nodes`, and exporting a mobile SQL View `v_dialogue_nodes` with sub-0.5ms node traversal latency.

**Architecture:** Expand `ScenarioBuilder` in `src/nlp/scenario_builder.py` to maintain 25+ structured branching scenarios. Add `insert_dialogue_scenarios_batch` to `DatabaseManager` in `src/db/staging_db.py` to resolve parent-child node relationships and sentence IDs. Add `run_scenario_step` to `main.py`. Update `SQLiteExporter` to create `v_dialogue_nodes` SQL View and benchmark `scenario_traversal_ms` (< 0.5 ms SLA).

**Tech Stack:** Python 3.10+, SQLite 3, pytest.

## Global Constraints

- **Scenario Catalog:** 25+ branching situational scenarios across 8 themes (Cafe/Restaurant, Hotels, Travel/Directions, Shopping, Airports/Customs, Job Interviews, Medical, Socializing).
- **Database Schema:** `dialogue_trees(id, title, topic, cefr_level, root_node_id)` and `dialogue_nodes(id, tree_id, parent_node_id, choice_label, speaker_role, sentence_id)`.
- **Mobile SQL View:** `v_dialogue_nodes` JOINing `dialogue_nodes` and `sentences` to output `node_id`, `tree_id`, `parent_node_id`, `choice_label`, `speaker_role`, `sentence_id`, `text_en`, `text_vi`, `cefr_level`, `audio_path`.
- **Latency SLA:** Scenario traversal query response time < 0.5 ms in `SQLiteExporter`.

---

### Task 1: Scenario Registry & ScenarioBuilder Expansion

**Files:**
- Modify: `src/nlp/scenario_builder.py`
- Create: `tests/test_scenario_builder.py`

**Interfaces:**
- Consumes: None.
- Produces: `ScenarioBuilder.build_all_scenarios() -> List[Dict[str, Any]]` returning 25+ branching scenario trees.

- [ ] **Step 1: Write failing unit test for `ScenarioBuilder.build_all_scenarios()`**

```python
import pytest
from src.nlp.scenario_builder import ScenarioBuilder

def test_build_all_scenarios_catalog():
    builder = ScenarioBuilder()
    scenarios = builder.build_all_scenarios()
    assert len(scenarios) >= 25

    topics = {s["topic"] for s in scenarios}
    assert "Dining" in topics
    assert "Travel & Directions" in topics
    assert "Hotel & Accommodation" in topics
    assert "Shopping & Retail" in topics

    for sc in scenarios:
        assert "title" in sc
        assert "topic" in sc
        assert "cefr_level" in sc
        assert len(sc["nodes"]) >= 3
        
        # Verify node indices and parent indices
        indices = {n["node_index"] for n in sc["nodes"]}
        assert 0 in indices  # Root node
        for n in sc["nodes"]:
            if n["parent_index"] is not None:
                assert n["parent_index"] in indices
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scenario_builder.py -v`
Expected: FAIL (`AttributeError: 'ScenarioBuilder' object has no attribute 'build_all_scenarios'`).

- [ ] **Step 3: Implement `build_all_scenarios()` in `src/nlp/scenario_builder.py`**

Expand `ScenarioBuilder` in `src/nlp/scenario_builder.py` to add `build_all_scenarios()` with 25+ structured branching scenarios covering all 8 situational themes.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scenario_builder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/nlp/scenario_builder.py tests/test_scenario_builder.py
git commit -m "feat(nlp): expand ScenarioBuilder with 25+ branching situational scenarios"
```

---

### Task 2: Database Scenario Batch Helpers (`DatabaseManager`)

**Files:**
- Modify: `src/db/staging_db.py`
- Create: `tests/test_scenario_db.py`

**Interfaces:**
- Consumes: Staging DB connection.
- Produces: `DatabaseManager.insert_dialogue_scenarios_batch(scenarios: List[Dict[str, Any]]) -> Tuple[int, int]` returning `(trees_count, nodes_count)`.

- [ ] **Step 1: Write failing unit test for `insert_dialogue_scenarios_batch`**

```python
import sqlite3
import pytest
from pathlib import Path
from src.db.staging_db import DatabaseManager

@pytest.fixture
def tmp_db(tmp_path) -> DatabaseManager:
    db_path = tmp_path / "staging.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_schema()
    return db_mgr

def test_insert_dialogue_scenarios_batch(tmp_db):
    scenarios = [
        {
            "title": "Ordering Coffee",
            "topic": "Dining",
            "cefr_level": "A2",
            "nodes": [
                {"node_index": 0, "parent_index": None, "speaker_role": "A", "choice_label": None, "text_en": "Hi! What can I get started for you?", "text_vi": "Xin chào! Bạn muốn dùng gì?"},
                {"node_index": 1, "parent_index": 0, "speaker_role": "B", "choice_label": "Hot Latte", "text_en": "I'd like a hot latte.", "text_vi": "Cho tôi 1 latte nóng."}
            ]
        }
    ]
    trees_cnt, nodes_cnt = tmp_db.insert_dialogue_scenarios_batch(scenarios)
    assert trees_cnt == 1
    assert nodes_cnt == 2

    conn = tmp_db.get_connection()
    row = conn.execute("SELECT title, root_node_id FROM dialogue_trees WHERE id = 1;").fetchone()
    assert row[0] == "Ordering Coffee"
    assert row[1] is not None

    node_row = conn.execute("SELECT parent_node_id, choice_label FROM dialogue_nodes WHERE tree_id = 1 AND choice_label = 'Hot Latte';").fetchone()
    assert node_row[0] == row[1]  # Parent is root node
    tmp_db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scenario_db.py -v`
Expected: FAIL (`AttributeError: 'DatabaseManager' object has no attribute 'insert_dialogue_scenarios_batch'`).

- [ ] **Step 3: Implement `insert_dialogue_scenarios_batch` in `src/db/staging_db.py`**

Add `insert_dialogue_scenarios_batch` and sentence auto-linking logic to `src/db/staging_db.py`:
- Checks/inserts `text_en` into `sentences` table to get `sentence_id`.
- Inserts `dialogue_trees` and `dialogue_nodes`.
- Resolves parent node IDs and root node ID.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scenario_db.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/db/staging_db.py tests/test_scenario_db.py
git commit -m "feat(db): add insert_dialogue_scenarios_batch helper with sentence auto-linking"
```

---

### Task 3: ETL Pipeline Integration (`main.py`)

**Files:**
- Modify: `main.py`
- Create: `tests/test_scenario_pipeline.py`

**Interfaces:**
- Consumes: Staging database.
- Produces: `run_scenario_step(db_mgr: DatabaseManager) -> Tuple[int, int]`.

- [ ] **Step 1: Write failing unit test for `run_scenario_step`**

```python
import pytest
from src.db.staging_db import DatabaseManager
from main import run_scenario_step

def test_run_scenario_step(tmp_path):
    db_path = tmp_path / "test_pipeline.db"
    db_mgr = DatabaseManager(db_path=db_path)
    db_mgr.init_schema()

    trees_count, nodes_count = run_scenario_step(db_mgr)
    assert trees_count >= 25
    assert nodes_count >= 75

    conn = db_mgr.get_connection()
    count = conn.execute("SELECT COUNT(*) FROM dialogue_trees;").fetchone()[0]
    assert count >= 25
    db_mgr.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scenario_pipeline.py -v`
Expected: FAIL (`ImportError: cannot import name 'run_scenario_step' from 'main'`).

- [ ] **Step 3: Implement `run_scenario_step` in `main.py`**

Add `run_scenario_step(db_mgr: DatabaseManager, args=None) -> Tuple[int, int]` to `main.py`:
- Connect `run_scenario_step` into Step 4D of `run_pipeline()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scenario_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_scenario_pipeline.py
git commit -m "feat(pipeline): add run_scenario_step to main.py ETL pipeline"
```

---

### Task 4: Mobile SQL View (`v_dialogue_nodes`) & SLA Benchmark

**Files:**
- Modify: `src/export/sqlite_exporter.py`
- Modify: `tests/test_sqlite_exporter.py`

**Interfaces:**
- Consumes: Packaged SQLite database.
- Produces: `v_dialogue_nodes` SQL View & `scenario_traversal_ms` SLA benchmark < 0.5 ms.

- [ ] **Step 1: Write failing unit test for `v_dialogue_nodes` view & benchmark**

```python
def test_v_dialogue_nodes_view_and_sla(dummy_db):
    conn = sqlite3.connect(str(dummy_db))
    conn.execute("CREATE TABLE IF NOT EXISTS dialogue_trees (id INTEGER PRIMARY KEY, title TEXT, topic TEXT, cefr_level TEXT, root_node_id INTEGER);")
    conn.execute("CREATE TABLE IF NOT EXISTS dialogue_nodes (id INTEGER PRIMARY KEY, tree_id INTEGER, parent_node_id INTEGER, choice_label TEXT, speaker_role TEXT, sentence_id INTEGER);")
    conn.execute("INSERT INTO dialogue_trees VALUES (1, 'Ordering Coffee', 'Dining', 'A2', 1);")
    conn.execute("INSERT INTO dialogue_nodes VALUES (1, 1, NULL, NULL, 'A', 1);")
    conn.execute("INSERT INTO dialogue_nodes VALUES (2, 1, 1, 'Hot Latte', 'B', 1);")
    conn.commit()
    conn.close()

    exporter = SQLiteExporter(db_path=dummy_db)
    exporter.optimize_and_package()

    conn = sqlite3.connect(str(dummy_db))
    # Check v_dialogue_nodes view exists
    row = conn.execute("SELECT node_id, choice_label, text_en FROM v_dialogue_nodes WHERE tree_id = 1 AND parent_node_id = 1;").fetchone()
    assert row is not None
    assert row[1] == 'Hot Latte'
    conn.close()

    benchmarks = exporter.benchmark_all_queries(iterations=20)
    assert "scenario_traversal_ms" in benchmarks
    assert benchmarks["scenario_traversal_ms"] < 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sqlite_exporter.py::test_v_dialogue_nodes_view_and_sla -v`
Expected: FAIL (assertion error because `v_dialogue_nodes` view or `scenario_traversal_ms` missing).

- [ ] **Step 3: Implement `v_dialogue_nodes` view & SLA benchmark in `SQLiteExporter`**

In `src/export/sqlite_exporter.py`:
- Add `v_dialogue_nodes` SQL View creation in `_migrate_schema_and_enums`.
- Add `scenario_traversal_ms` query benchmark to `benchmark_all_queries`:
  `SELECT node_id, speaker_role, choice_label, text_en, text_vi FROM v_dialogue_nodes WHERE tree_id = 1 AND parent_node_id = 1;`

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_sqlite_exporter.py::test_v_dialogue_nodes_view_and_sla -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/export/sqlite_exporter.py tests/test_sqlite_exporter.py
git commit -m "feat(export): add v_dialogue_nodes view and scenario_traversal_ms SLA benchmark"
```
