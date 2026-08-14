# Core 3000 Pack Builder Decomposition & Quality Assurance Engine (Phase 1)

## 1. Executive Summary

This specification outlines the decomposition of the legacy monolithic `core_pack_builder.py` (793 LOC) into three decoupled, testable, and maintainable modules:
1. `core_selector.py`: Frequency ranking, noise filtering, contraction normalization, CEFR assignment, and NGSL validation.
2. `core_enricher.py`: Rigorous 5-point quality gate validation (EN definition, VI translation, IPA phonetics, example sentences, thematic topic).
3. `core_exporter.py`: Optimized SQLite packaging (`core_3000.db`) with index generation, WAL mode, metadata, and comprehensive markdown quality audit reporting (`quality_report.md`).

This completes Phase 1 of the remediation plan for the Pipeline V2 engine.

---

## 2. Architecture & Component Decomposition

```
                   ┌──────────────────────────────────────┐
                   │          DuckDB Staging DB           │
                   └──────────────────┬───────────────────┘
                                      │
                                      ▼
                   ┌──────────────────────────────────────┐
                   │           CoreSelector               │
                   │ • Frequency ranking (SUBTLEX-US)     │
                   │ • Noise POS & Contraction filtering  │
                   │ • CEFR rank threshold mapping        │
                   │ • NGSL headword overlap check        │
                   └──────────────────┬───────────────────┘
                                      │ (Top 3000 words)
                                      ▼
                   ┌──────────────────────────────────────┐
                   │            CoreEnricher              │
                   │ • Gate 1: English Definition         │
                   │ • Gate 2: Vietnamese Translation     │
                   │ • Gate 3: IPA Transcription          │
                   │ • Gate 4: Linked Sentences           │
                   │ • Gate 5: Thematic Topic             │
                   └──────────────────┬───────────────────┘
                                      │ (Enriched words + Quality metrics)
                                      ▼
                   ┌──────────────────────────────────────┐
                   │            CoreExporter              │
                   │ ├── core_3000.db (SQLite Pack)       │
                   │ └── quality_report.md (Audit Report) │
                   └──────────────────────────────────────┘
```

---

## 3. Detailed Component Specifications

### 3.1 `CoreSelector` (`src/export/core_selector.py`)

Responsible for selecting the highest-quality top 3,000 core English vocabulary words from the staging database.

#### Responsibilities & Logic:
- **Frequency Ordering**: Orders candidates by `frequency_rank` (SUBTLEX-US), prioritizing headwords with lowest rank numbers.
- **POS & Noise Filtering**: Excludes non-headword POS categories: `{"name", "prefix", "suffix", "symbol", "particle", "num", "punct", "character", "contraction"}`.
- **Contraction & Normalization**: Expands contractions (e.g. `don't` -> `do`, `can't` -> `can`) using `CONTRACTION_MAP` to avoid duplicate grammatical variants.
- **CEFR Level Assignment**: Assigns CEFR bands based on frequency rank:
  - `A1`: rank 1 - 500
  - `A2`: rank 501 - 1,500
  - `B1`: rank 1,501 - 3,500
  - `B2`: rank 3,501 - 7,000
  - `C1`: rank 7,001 - 15,000
  - `C2`: rank > 15,000
- **NGSL Validation**: Checks candidate overlap with the New General Service List (NGSL) and attaches validation flags.

#### Interface:
```python
@dataclass
class SelectedWord:
    id: int
    lemma: str
    pos: str
    frequency_rank: Optional[int]
    cefr_level: str
    in_ngsl: bool
    source: str

class CoreSelector:
    def select_core_words(
        self,
        db_mgr: DuckDBManager,
        limit: int = 3000,
        ngsl_path: Optional[Path] = None,
    ) -> List[SelectedWord]:
        ...
```

---

### 3.2 `CoreEnricher` (`src/export/core_enricher.py`)

Responsible for validating that each selected word satisfies the 5 Quality Gates required for the production iOS application bundle.

#### 5 Quality Gates:
1. **Gate 1: English Definition (`def_en`)**: Must have >= 1 valid definition string (length >= 5 chars).
2. **Gate 2: Vietnamese Translation (`def_vi`)**: Must have a Vietnamese translation that passes `VietnameseValidator` (contains valid Vietnamese diacritics/phonemes, not an English echo or raw untranslated text).
3. **Gate 3: IPA Pronunciation (`ipa`)**: Must have `ipa_uk` or `ipa_us` populated.
4. **Gate 4: Linked Sentence Examples (`sentences`)**: Must have at least 1 linked contextual sentence in `word_sentences`.
5. **Gate 5: Thematic Topic (`topic`)**: Must be categorized into a thematic topic in `word_topics`.

#### Interface & Data Structures:
```python
@dataclass
class QualityGateResult:
    word_id: int
    lemma: str
    has_def_en: bool
    has_def_vi: bool
    has_ipa: bool
    has_sentence: bool
    has_topic: bool
    passed_all: bool
    missing_fields: List[str]

@dataclass
class EnrichmentSummary:
    total_words: int
    passed_all_gates: int
    def_en_coverage: float
    def_vi_coverage: float
    ipa_coverage: float
    sentence_coverage: float
    topic_coverage: float
    failed_words: List[QualityGateResult]

class CoreEnricher:
    def validate_and_enrich(
        self,
        db_mgr: DuckDBManager,
        selected_words: List[SelectedWord],
    ) -> Tuple[List[Dict[str, Any]], EnrichmentSummary]:
        ...
```

---

### 3.3 `CoreExporter` (`src/export/core_exporter.py`)

Responsible for creating the optimized SQLite database `core_3000.db` and writing the detailed audit markdown `quality_report.md`.

#### Responsibilities:
1. **SQLite Bundle Packaging**:
   - Executes `SQLITE_SCHEMA` and inserts words, definitions, sentences, word_sentences, reflex_drills, word_topics, word_relations, dialogue_trees, dialogue_nodes.
   - Creates indexes (`SQLITE_INDEXES`).
   - Sets pragmas (`journal_mode = WAL`, `synchronous = NORMAL`, `optimize`).
   - Populates `dataset_metadata` table with build timestamp, version, row counts.
2. **Quality Report Generation**:
   - Writes `data/output/quality_report.md` with:
     - Total words, gate pass rate, coverage percentage per field.
     - NGSL overlap percentage.
     - CEFR distribution breakdown (A1, A2, B1, B2, C1).
     - Breakdown by thematic topics.
     - List of items requiring attention (if any).

#### Interface:
```python
class CoreExporter:
    def export_core_bundle(
        self,
        db_mgr: DuckDBManager,
        target_path: Path,
        report_path: Optional[Path] = None,
        core_limit: int = 3000,
        ngsl_path: Optional[Path] = None,
    ) -> int:
        ...

    def write_quality_report(
        self,
        summary: EnrichmentSummary,
        selector_stats: Dict[str, Any],
        output_path: Path,
    ) -> None:
        ...
```

---

## 4. Pipeline Step Integration

`ExportCore3000Step` in `src/pipeline/steps/export_core3000.py` will orchestrate the 3 components:
```python
class ExportCore3000Step(BaseStep):
    name = "export_core3000"
    description = "Build and export curated core_3000.db iOS bundle with quality audit"
    depends_on = ["export_sqlite"]
    produces = ["core_3000.db", "quality_report.md"]
    execution_type = "cpu"

    def run(self, ctx: PipelineContext) -> StepResult:
        exporter = CoreExporter()
        report_path = OUTPUT_DIR / "quality_report.md"
        count = exporter.export_core_bundle(
            db_mgr=ctx.db,
            target_path=OUTPUT_DIR / "core_3000.db",
            report_path=report_path,
            core_limit=3000,
            ngsl_path=NGSL_PATH,
        )
        return StepResult(
            step_name=self.name,
            status=StepStatus.SUCCESS,
            items_processed=count,
            message=f"Exported {count} core words with quality report at {report_path}",
        )
```

---

## 5. Cleanup & Deprecation

- Delete `src/export/core_pack_builder.py` (793 LOC).
- Ensure no remaining imports reference `core_pack_builder`.

---

## 6. Verification & Test Plan

1. **Unit Tests**:
   - `tests/test_export/test_core_selector.py`: Verify contraction mapping, noise filtering, CEFR assignment, NGSL overlap.
   - `tests/test_export/test_core_enricher.py`: Verify all 5 quality gates with mocked/fixture data.
   - `tests/test_export/test_core_exporter.py`: Verify SQLite table structure, indexes, and `quality_report.md` generation.
2. **Integration Test**:
   - `tests/test_pipeline/test_export_core3000_step.py`: Execute full step against a populated staging DuckDB database and verify both `core_3000.db` and `quality_report.md` exist and are valid.
