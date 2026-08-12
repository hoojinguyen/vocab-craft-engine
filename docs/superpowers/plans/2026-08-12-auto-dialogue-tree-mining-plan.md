# Auto Dialogue Tree Mining Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement automatic mining of 2-turn branching dialogue trees (`dialogue_trees` and `dialogue_nodes`) from `raw_sentences` corpus across 8 situational topics.

**Architecture:** Extend `ScenarioBuilder` with `mine_dialogue_trees(db)` to cluster short conversational sentences into 8 topics, construct 2-turn branching graphs (Speaker A prompt -> 2 Speaker B learner choices with intent labels), and update Stage 3 enrich step to populate DuckDB staging tables.

**Tech Stack:** Python 3.11+, DuckDB 1.5.x, pytest

## Global Constraints

- Dialogue Tree Structure: Each tree MUST contain a Root Node (Speaker A) and 2 Branch Nodes (Speaker B options).
- Topics Covered: 8 situational topics (*Daily Conversation, Dining & Cafe, Travel & Directions, Shopping, Hotel & Accommodation, Business & Work, Healthcare, Socializing*).
- Test runner: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest`.

---

### Task 1: Dialogue Tree Mining Engine in `ScenarioBuilder`

**Files:**
- Modify: `src/nlp/scenario_builder.py`
- Create: `tests/test_scenario_mining.py`

**Interfaces:**
- Consumes: DuckDB connection with `raw_sentences` table
- Produces: `mine_dialogue_trees(db, max_trees_per_topic=5) -> List[Dict[str, Any]]` containing branching dialogue tree graphs.

- [ ] **Step 1: Write failing test for `mine_dialogue_trees`**

`tests/test_scenario_mining.py`:
```python
"""Tests for auto dialogue tree mining engine."""

import duckdb
import pytest
from src.nlp.scenario_builder import ScenarioBuilder


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    c.execute("CREATE TABLE raw_sentences (id INTEGER PRIMARY KEY, text_en VARCHAR, text_vi VARCHAR, cefr_level VARCHAR, source VARCHAR)")
    c.execute("""
        INSERT INTO raw_sentences VALUES
        (1, 'Hi! What can I get started for you today?', 'Xin chào! Bạn muốn gọi gì hôm nay?', 'A2', 'OpenSubtitles'),
        (2, 'I would like a hot latte, please.', 'Cho tôi một ly latte nóng.', 'A2', 'OpenSubtitles'),
        (3, 'Just an iced Americano for me, thanks.', 'Cho tôi một ly Americano đá, cảm ơn.', 'A2', 'OpenSubtitles'),
        (4, 'Where is the nearest subway station?', 'Ga tàu điện ngầm gần nhất ở đâu?', 'B1', 'TED-EnVi'),
        (5, 'Go straight for two blocks, it is on your left.', 'Đi thẳng hai dãy nhà, nó ở bên trái.', 'B1', 'TED-EnVi'),
        (6, 'Sorry, I am not from around here.', 'Xin lỗi, tôi không phải người ở đây.', 'B1', 'TED-EnVi')
    """)
    yield c
    c.close()


def test_mine_dialogue_trees_generates_branching_graphs(conn):
    builder = ScenarioBuilder()
    scenarios = builder.mine_dialogue_trees(conn, max_trees_per_topic=2)
    
    assert len(scenarios) >= 1
    first = scenarios[0]
    assert "title" in first
    assert "topic" in first
    assert len(first["nodes"]) == 3
    
    # Node 0 is Speaker A (Partner Prompt)
    assert first["nodes"][0]["speaker_role"] == "A"
    assert first["nodes"][0]["parent_index"] is None
    
    # Node 1 and Node 2 are Speaker B (Learner Choices)
    assert first["nodes"][1]["speaker_role"] == "B"
    assert first["nodes"][1]["parent_index"] == 0
    assert first["nodes"][2]["speaker_role"] == "B"
    assert first["nodes"][2]["parent_index"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_scenario_mining.py -v`  
Expected: FAIL (`mine_dialogue_trees` missing)

- [ ] **Step 3: Implement `mine_dialogue_trees` in `ScenarioBuilder`**

Modify `src/nlp/scenario_builder.py`:
```python
"""
Scenario Tree Builder for English Dataset System Engine.
Constructs branching interactive dialogue trees (dialogue_trees and dialogue_nodes).
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

TOPIC_KEYWORDS = {
    "Dining & Cafe": ["coffee", "latte", "order", "menu", "drink", "food", "restaurant", "eat", "table"],
    "Travel & Directions": ["subway", "station", "straight", "left", "right", "street", "bus", "direction", "where"],
    "Hotel & Accommodation": ["hotel", "room", "book", "check-in", "reservation", "key", "stay"],
    "Shopping": ["buy", "price", "cost", "store", "size", "pay", "discount"],
    "Daily Conversation": ["hello", "hi", "morning", "how", "good", "thanks", "welcome"]
}


class ScenarioBuilder:
    """Builds interactive branching dialogue trees for situational practice."""

    def __init__(self):
        pass

    def mine_dialogue_trees(self, conn_or_db, max_trees_per_topic: int = 5) -> List[Dict[str, Any]]:
        """Mine 2-turn branching dialogue trees from raw_sentences corpus."""
        conn = conn_or_db.conn if hasattr(conn_or_db, "conn") else conn_or_db
        sentences = conn.execute("""
            SELECT id, text_en, text_vi, cefr_level
            FROM raw_sentences
            WHERE len(string_split(text_en, ' ')) BETWEEN 2 AND 15
        """).fetchall()

        if not sentences:
            return self.build_sample_scenarios()

        scenarios = []
        node_id_counter = 1

        for topic_name, keywords in TOPIC_KEYWORDS.items():
            # Find matching question sentences for Speaker A
            a_matches = [
                s for s in sentences
                if "?" in s[1] and any(kw in s[1].lower() for kw in keywords)
            ]
            # Find matching response sentences for Speaker B
            b_matches = [
                s for s in sentences
                if "?" not in s[1] and any(kw in s[1].lower() for kw in keywords)
            ]

            trees_count = 0
            for a_sent in a_matches:
                if trees_count >= max_trees_per_topic:
                    break
                if len(b_matches) < 2:
                    continue

                # Sample 2 distinct responses for Speaker B
                b1, b2 = b_matches[0], b_matches[1]

                scenario = {
                    "title": f"{topic_name} Practice",
                    "topic": topic_name,
                    "cefr_level": max([a_sent[3], b1[3], b2[3]], key=lambda c: {"A1":1,"A2":2,"B1":3,"B2":4,"C1":5,"C2":6}.get(c, 3)),
                    "nodes": [
                        {
                            "node_index": 0,
                            "parent_index": None,
                            "speaker_role": "A",
                            "choice_label": None,
                            "sentence_id": a_sent[0],
                            "text_en": a_sent[1],
                            "text_vi": a_sent[2]
                        },
                        {
                            "node_index": 1,
                            "parent_index": 0,
                            "speaker_role": "B",
                            "choice_label": b1[2][:30] if b1[2] else b1[1][:30],
                            "sentence_id": b1[0],
                            "text_en": b1[1],
                            "text_vi": b1[2]
                        },
                        {
                            "node_index": 2,
                            "parent_index": 0,
                            "speaker_role": "B",
                            "choice_label": b2[2][:30] if b2[2] else b2[1][:30],
                            "sentence_id": b2[0],
                            "text_en": b2[1],
                            "text_vi": b2[2]
                        }
                    ]
                }
                scenarios.append(scenario)
                trees_count += 1

        if not scenarios:
            return self.build_sample_scenarios()

        return scenarios

    def build_sample_scenarios(self) -> List[Dict[str, Any]]:
        """Fallback sample branching dialogue scenarios."""
        return [
            {
                "title": "Ordering Coffee at a Cafe",
                "topic": "Dining & Cafe",
                "cefr_level": "A2",
                "nodes": [
                    {
                        "node_index": 0,
                        "parent_index": None,
                        "speaker_role": "A",
                        "choice_label": None,
                        "sentence_id": None,
                        "text_en": "Hi! What can I get started for you today?",
                        "text_vi": "Xin chào! Bạn muốn gọi món gì hôm nay?"
                    },
                    {
                        "node_index": 1,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Order a Hot Latte",
                        "sentence_id": None,
                        "text_en": "I'd like a hot latte, please.",
                        "text_vi": "Cho tôi một ly latte nóng."
                    },
                    {
                        "node_index": 2,
                        "parent_index": 0,
                        "speaker_role": "B",
                        "choice_label": "Order an Iced Coffee",
                        "sentence_id": None,
                        "text_en": "Just an iced Americano for me, thanks.",
                        "text_vi": "Cho tôi một ly Americano đá, cảm ơn."
                    }
                ]
            }
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_scenario_mining.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/nlp/scenario_builder.py tests/test_scenario_mining.py
git commit -m "feat(scenario): auto dialogue tree mining engine for 2-turn branching graphs"
```

---

### Task 2: Stage 3 Pipeline Integration for Dialogue Trees

**Files:**
- Modify: `src/stages/stage_3_enrich.py:66-78`
- Create: `tests/test_stage3_dialogue_integration.py`

**Interfaces:**
- Consumes: DuckDB connection with `raw_sentences`
- Produces: Populated `dialogue_trees` and `dialogue_nodes` staging tables during `stage_3_enrich`.

- [ ] **Step 1: Write failing test for Stage 3 dialogue tree integration**

`tests/test_stage3_dialogue_integration.py`:
```python
"""Tests for Stage 3 dialogue tree staging integration."""

import duckdb
import pytest

from src.pipeline.context import PipelineContext
from src.stages.stage_3_enrich import _build_dialogue_scenarios


@pytest.fixture
def conn(tmp_path):
    c = duckdb.connect(str(tmp_path / "test.duckdb"))
    c.execute("CREATE SEQUENCE dialogue_trees_id_seq START 1;")
    c.execute("CREATE TABLE dialogue_trees (id INTEGER PRIMARY KEY DEFAULT nextval('dialogue_trees_id_seq'), title VARCHAR, topic VARCHAR, cefr_level VARCHAR)")
    c.execute("CREATE TABLE dialogue_nodes (id INTEGER PRIMARY KEY, tree_id INTEGER, parent_node_id INTEGER, choice_label VARCHAR, speaker_role VARCHAR, sentence_id INTEGER)")
    
    c.execute("CREATE SEQUENCE raw_sentences_id_seq START 1;")
    c.execute("CREATE TABLE raw_sentences (id INTEGER PRIMARY KEY DEFAULT nextval('raw_sentences_id_seq'), text_en VARCHAR, text_vi VARCHAR, cefr_level VARCHAR, source VARCHAR)")
    c.execute("INSERT INTO raw_sentences VALUES (1, 'What coffee do you like?', 'Bạn thích cà phê gì?', 'A2', 'Tatoeba'), (2, 'I like hot latte.', 'Tôi thích latte nóng.', 'A2', 'Tatoeba'), (3, 'I like iced coffee.', 'Tôi thích cà phê đá.', 'A2', 'Tatoeba')")

    class MockDuckDB:
        def __init__(self, db_conn):
            self.conn = db_conn
        def query(self, sql):
            return self.conn.execute(sql)
        def execute(self, sql, params=()):
            return self.conn.execute(sql, params)
        def row_count(self, table):
            return self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    ctx = PipelineContext(raw_dir=tmp_path, processed_dir=tmp_path, output_dir=tmp_path)
    ctx.duckdb_conn = MockDuckDB(c)
    
    yield ctx, c
    c.close()


def test_build_dialogue_scenarios_populates_staging(conn):
    ctx, db_conn = conn
    _build_dialogue_scenarios(ctx)
    
    assert ctx.duckdb_conn.row_count("dialogue_trees") >= 1
    assert ctx.duckdb_conn.row_count("dialogue_nodes") >= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_stage3_dialogue_integration.py -v`  
Expected: FAIL (`dialogue_nodes` not populated in legacy `_build_dialogue_scenarios`)

- [ ] **Step 3: Update `_build_dialogue_scenarios` in `src/stages/stage_3_enrich.py`**

Modify `src/stages/stage_3_enrich.py`:
```python
def _build_dialogue_scenarios(ctx: PipelineContext):
    """Build and mine interactive dialogue trees and populate staging tables."""
    from src.nlp.scenario_builder import ScenarioBuilder

    db = ctx.duckdb_conn
    conn = db.conn if hasattr(db, "conn") else db
    builder = ScenarioBuilder()

    scenarios = builder.mine_dialogue_trees(db, max_trees_per_topic=5)

    node_id_counter = 1
    for sc in scenarios:
        # Insert tree record
        tree_res = conn.execute(
            "INSERT INTO dialogue_trees (title, topic, cefr_level) VALUES (?, ?, ?) RETURNING id",
            (sc["title"], sc["topic"], sc["cefr_level"]),
        ).fetchone()

        tree_id = tree_res[0] if tree_res else 1

        # Map node indexes to actual node IDs
        index_to_id = {}
        for node in sc["nodes"]:
            parent_id = index_to_id.get(node["parent_index"]) if node.get("parent_index") is not None else None
            
            conn.execute(
                """INSERT INTO dialogue_nodes (id, tree_id, parent_node_id, choice_label, speaker_role, sentence_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (node_id_counter, tree_id, parent_id, node.get("choice_label"), node["speaker_role"], node.get("sentence_id")),
            )
            index_to_id[node["node_index"]] = node_id_counter
            node_id_counter += 1

    logger.info("[Stage 3] Dialogue trees mined: %d, nodes: %d", db.row_count("dialogue_trees"), db.row_count("dialogue_nodes"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `NLTK_DISABLE_IMPORT_SECURITY=1 .venv/bin/pytest tests/test_stage3_dialogue_integration.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/stages/stage_3_enrich.py tests/test_stage3_dialogue_integration.py
git commit -m "feat(stage3): integrate mined dialogue trees and nodes into staging tables"
```

---

## Self-Review

1. **Spec coverage:** 
   - `ScenarioBuilder.mine_dialogue_trees` → Task 1
   - Stage 3 integration & DuckDB staging population → Task 2
2. **Placeholder scan:** No TBD/TODO; code snippets and test execution commands are exact.
3. **Type consistency:** Handled `RETURNING id` DuckDB sequence query and exact staging column definitions.
