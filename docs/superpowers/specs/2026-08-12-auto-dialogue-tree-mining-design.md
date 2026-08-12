# Auto Dialogue Tree Mining Design Spec

> **Date:** 2026-08-12  
> **Status:** APPROVED BY USER  
> **Goal:** Mine parallel sentence corpora to construct 2-turn branching dialogue trees (`dialogue_trees` and `dialogue_nodes`) across 8 situational topics without commercial LLM API costs.

---

## 1. Overview & Objectives

This design automates situational dialogue scenario generation by:
1. **Topic Clustering:** Clustering short conversational sentences (2-12 words) from `raw_sentences` into 8 situational topics (*Daily Conversation, Dining & Cafe, Travel & Directions, Shopping, Hotel & Accommodation, Business & Work, Healthcare, Socializing*).
2. **Branching 2-Turn Graph Construction:** Building graph trees containing a Partner Prompt (Speaker A) and 2 distinct Learner Response Options (Speaker B) with intent-summarized `choice_label`s.
3. **Stage 3 Pipeline Integration:** Automatically populating `dialogue_trees` and `dialogue_nodes` staging tables during Stage 3 execution.

---

## 2. Component Design Details

### 2.1 Dialogue Mining Engine (`src/nlp/scenario_builder.py`)
- **Topic Classifier:** Maps candidate sentence pairs to 8 situational topics using `TopicMapper` keyword rules.
- **Tree Builder (`mine_dialogue_trees`):**
  - **Root Node (Speaker A):** Question or prompt sentence from partner (`speaker_role = 'A'`, `parent_node_id = NULL`).
  - **Branch Node 1 (Speaker B - Option 1):** Primary / affirmative response (`speaker_role = 'B'`, `choice_label = 'Option 1 Intent'`, `parent_node_id = Root.id`).
  - **Branch Node 2 (Speaker B - Option 2):** Alternative / decline response (`speaker_role = 'B'`, `choice_label = 'Option 2 Intent'`, `parent_node_id = Root.id`).
  - **CEFR Assignment:** Set tree `cefr_level` to the maximum CEFR level among constituent sentences.

### 2.2 Stage 3 Integration (`src/stages/stage_3_enrich.py`)
- Update `_build_dialogue_scenarios` to invoke `ScenarioBuilder.mine_dialogue_trees(db)` and write mined dialogue trees/nodes into DuckDB staging tables.

---

## 3. Verification Plan

### Automated Tests
1. **Scenario Builder Mining Tests:** Test `mine_dialogue_trees` creates 2-turn branching graphs with correct speaker roles and `choice_label`s.
2. **Stage 3 Integration Tests:** Verify `dialogue_trees` and `dialogue_nodes` staging tables populated correctly during Stage 3 execution.
