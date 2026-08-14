"""Core 3000 SQLite Bundle Exporter & Quality Report Generator."""

from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from src.db.duckdb_manager import DuckDBManager
from src.export.core_enricher import CoreEnricher, EnrichmentSummary
from src.export.core_selector import CoreSelector
from src.export.schema import SQLITE_INDEXES, SQLITE_SCHEMA

logger = logging.getLogger(__name__)


class CoreExporter:
    """Exports curated core vocabulary database and detailed quality audit report."""

    def __init__(self):
        self.selector = CoreSelector()
        self.enricher = CoreEnricher()

    def export_core_bundle(
        self,
        db_mgr: DuckDBManager,
        target_path: Path,
        report_path: Optional[Path] = None,
        core_limit: int = 3000,
        ngsl_path: Optional[Path] = None,
    ) -> int:
        target_file = Path(target_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        if target_file.exists():
            target_file.unlink()

        # 1. Select headwords
        selected_words = self.selector.select_core_words(db_mgr, limit=core_limit, ngsl_path=ngsl_path)
        if not selected_words:
            logger.warning("No words found in staging DB for core bundle export")
            return 0

        # 2. Enrich & Audit Quality Gates
        enriched_entries, summary = self.enricher.validate_and_enrich(db_mgr, selected_words)

        # 3. Create SQLite Database
        s_conn = sqlite3.connect(str(target_file))
        s_cursor = s_conn.cursor()
        s_cursor.execute("PRAGMA synchronous = OFF;")
        s_cursor.execute("PRAGMA journal_mode = MEMORY;")
        s_cursor.execute("PRAGMA temp_store = MEMORY;")
        s_cursor.execute("PRAGMA foreign_keys = OFF;")
        s_cursor.executescript(SQLITE_SCHEMA)
        s_conn.commit()

        d_conn = db_mgr.get_connection()
        core_word_ids = [w.id for w in selected_words]
        id_set_str = ", ".join(str(wid) for wid in core_word_ids)

        # Insert words
        words_to_insert = [
            (
                e["id"], e["lemma"], e["pos"], e["ipa_uk"], e["ipa_us"],
                e["frequency_rank"], e["cefr_level"], e["source"]
            )
            for e in enriched_entries
        ]
        s_cursor.executemany("""
            INSERT INTO words (id, lemma, pos, ipa_uk, ipa_us, frequency_rank, cefr_level, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, words_to_insert)

        # Insert definitions
        defs_rows = d_conn.execute(f"""
            SELECT id, word_id, definition_en, definition_vi, example, source
            FROM definitions WHERE word_id IN ({id_set_str})
        """).fetchall()
        s_cursor.executemany("""
            INSERT INTO definitions (id, word_id, definition_en, definition_vi, example, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, defs_rows)

        # Insert word_sentences and sentences
        ws_rows = d_conn.execute(f"""
            SELECT word_id, sentence_id FROM word_sentences WHERE word_id IN ({id_set_str})
        """).fetchall()
        s_cursor.executemany("INSERT OR IGNORE INTO word_sentences (word_id, sentence_id) VALUES (?, ?)", ws_rows)

        core_sent_ids = list({r[1] for r in ws_rows})
        if core_sent_ids:
            sent_set_str = ", ".join(str(sid) for sid in core_sent_ids)
            sent_rows = d_conn.execute(f"""
                SELECT id, text_en, text_vi, difficulty_score, cefr_level, audio_path, source
                FROM sentences WHERE id IN ({sent_set_str})
            """).fetchall()
            s_cursor.executemany("""
                INSERT OR IGNORE INTO sentences (id, text_en, text_vi, difficulty_score, cefr_level, audio_path, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, sent_rows)

            drills_rows = d_conn.execute(f"""
                SELECT id, sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms
                FROM reflex_drills WHERE sentence_id IN ({sent_set_str})
            """).fetchall()
            s_cursor.executemany("""
                INSERT OR IGNORE INTO reflex_drills (id, sentence_id, drill_type, prompt_text, correct_answer, distractors_json, target_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, drills_rows)

        # Insert topics and relations
        topics_rows = d_conn.execute(f"""
            SELECT word_id, topic, raw_topic FROM word_topics WHERE word_id IN ({id_set_str})
        """).fetchall()
        s_cursor.executemany("INSERT OR IGNORE INTO word_topics (word_id, topic, raw_topic) VALUES (?, ?, ?)", topics_rows)

        rel_rows = d_conn.execute(f"""
            SELECT id, word_id, relation_type, target_text, target_word_id, inverted, source
            FROM word_relations WHERE word_id IN ({id_set_str})
        """).fetchall()
        s_cursor.executemany("""
            INSERT OR IGNORE INTO word_relations (id, word_id, relation_type, target_text, target_word_id, inverted, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rel_rows)

        # Insert dialogue trees and nodes
        tree_rows = d_conn.execute("SELECT id, title, topic, cefr_level, root_node_id FROM dialogue_trees").fetchall()
        s_cursor.executemany("INSERT OR IGNORE INTO dialogue_trees (id, title, topic, cefr_level, root_node_id) VALUES (?, ?, ?, ?, ?)", tree_rows)

        node_rows = d_conn.execute("SELECT id, tree_id, parent_node_id, choice_label, speaker_role, sentence_id FROM dialogue_nodes").fetchall()
        s_cursor.executemany("INSERT OR IGNORE INTO dialogue_nodes (id, tree_id, parent_node_id, choice_label, speaker_role, sentence_id) VALUES (?, ?, ?, ?, ?, ?)", node_rows)

        s_conn.commit()
        s_cursor.executescript(SQLITE_INDEXES)

        # Insert metadata
        now_str = datetime.now(timezone.utc).isoformat()
        metadata_entries = [
            ("version", "2.0"),
            ("bundle_type", "core_3000"),
            ("build_timestamp", now_str),
            ("core_words_count", str(len(words_to_insert))),
            ("definitions_count", str(len(defs_rows))),
            ("sentences_count", str(len(core_sent_ids))),
            ("passed_all_quality_gates", str(summary.passed_all_gates)),
        ]
        s_cursor.executemany("INSERT OR REPLACE INTO dataset_metadata (key, value) VALUES (?, ?)", metadata_entries)
        s_conn.commit()

        s_cursor.execute("PRAGMA foreign_keys = ON;")
        s_cursor.execute("PRAGMA journal_mode = WAL;")
        s_cursor.execute("PRAGMA optimize;")
        s_conn.close()

        # 4. Write Quality Report Markdown
        if report_path:
            self.write_quality_report(summary, selected_words, Path(report_path))

        logger.info("Exported Core %d SQLite bundle (%d words)", core_limit, len(words_to_insert))
        return len(words_to_insert)

    def write_quality_report(
        self,
        summary: EnrichmentSummary,
        selected_words: List[Any],
        output_path: Path,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cefr_counts: Dict[str, int] = {}
        for w in selected_words:
            cefr_counts[w.cefr_level] = cefr_counts.get(w.cefr_level, 0) + 1

        ngsl_count = sum(1 for w in selected_words if getattr(w, "in_ngsl", False))
        ngsl_pct = (ngsl_count / summary.total_words * 100) if summary.total_words else 0.0
        pass_pct = (summary.passed_all_gates / summary.total_words * 100) if summary.total_words else 0.0

        md = f"""# Core 3000 Quality Audit Report

**Generated:** {now_str}  
**Total Selected Headwords:** {summary.total_words:,}  
**Pass All Quality Gates:** {summary.passed_all_gates:,} ({pass_pct:.1f}%)  
**NGSL Overlap:** {ngsl_count:,} ({ngsl_pct:.1f}%)

---

## 1. Quality Gate Coverage

| Quality Gate | Covered Words | Coverage Ratio | Target | Status |
| :--- | :---: | :---: | :---: | :---: |
| **English Definitions** | {int(summary.def_en_coverage * summary.total_words):,} | {summary.def_en_coverage * 100:.1f}% | 100% | {'✅ Pass' if summary.def_en_coverage >= 0.95 else '⚠️ Needs Review'} |
| **Vietnamese Translations** | {int(summary.def_vi_coverage * summary.total_words):,} | {summary.def_vi_coverage * 100:.1f}% | 90% | {'✅ Pass' if summary.def_vi_coverage >= 0.90 else '⚠️ Needs Review'} |
| **IPA Pronunciations** | {int(summary.ipa_coverage * summary.total_words):,} | {summary.ipa_coverage * 100:.1f}% | 95% | {'✅ Pass' if summary.ipa_coverage >= 0.95 else '⚠️ Needs Review'} |
| **Contextual Sentences** | {int(summary.sentence_coverage * summary.total_words):,} | {summary.sentence_coverage * 100:.1f}% | 85% | {'✅ Pass' if summary.sentence_coverage >= 0.85 else '⚠️ Needs Review'} |
| **Thematic Topics** | {int(summary.topic_coverage * summary.total_words):,} | {summary.topic_coverage * 100:.1f}% | 95% | {'✅ Pass' if summary.topic_coverage >= 0.95 else '⚠️ Needs Review'} |

---

## 2. CEFR Level Distribution

| CEFR Level | Word Count | Percentage |
| :---: | :---: | :---: |
"""
        for lvl in ["A1", "A2", "B1", "B2", "C1", "C2"]:
            cnt = cefr_counts.get(lvl, 0)
            pct = (cnt / summary.total_words * 100) if summary.total_words else 0.0
            md += f"| **{lvl}** | {cnt:,} | {pct:.1f}% |\n"

        md += "\n---\n\n## 3. Defect Samples (First 20 items requiring attention)\n\n"
        defects = [r for r in summary.gate_results if not r.passed_all][:20]
        if not defects:
            md += "*All words successfully passed 100% of quality gates!*\n"
        else:
            md += "| Word | Missing Gates |\n| :--- | :--- |\n"
            for d in defects:
                md += f"| `{d.lemma}` | {', '.join(d.missing_fields)} |\n"

        output_path.write_text(md, encoding="utf-8")
        logger.info("Saved Core 3000 quality report to %s", output_path)
