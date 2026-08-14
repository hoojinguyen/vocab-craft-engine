"""Core 3000 Quality Gate Enricher and Auditor."""

from dataclasses import dataclass, field
import logging
from typing import Any, Dict, List, Set, Tuple

from src.db.duckdb_manager import DuckDBManager
from src.enrichment.vi_validator import VietnameseValidator
from src.export.core_selector import SelectedWord

logger = logging.getLogger(__name__)


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
    missing_fields: List[str] = field(default_factory=list)


@dataclass
class EnrichmentSummary:
    total_words: int
    passed_all_gates: int
    def_en_coverage: float
    def_vi_coverage: float
    ipa_coverage: float
    sentence_coverage: float
    topic_coverage: float
    gate_results: List[QualityGateResult] = field(default_factory=list)


class CoreEnricher:
    """Validates and measures the 5 quality gates for core vocabulary words."""

    def __init__(self):
        self.vi_validator = VietnameseValidator()

    def validate_and_enrich(
        self,
        db_mgr: DuckDBManager,
        selected_words: List[SelectedWord],
    ) -> Tuple[List[Dict[str, Any]], EnrichmentSummary]:
        if not selected_words:
            return [], EnrichmentSummary(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0)

        conn = db_mgr.get_connection()
        word_ids = [w.id for w in selected_words]
        id_set_str = ", ".join(str(wid) for wid in word_ids)

        # 1. Fetch word IPA details
        word_rows = conn.execute(f"""
            SELECT id, ipa_uk, ipa_us FROM words WHERE id IN ({id_set_str})
        """).fetchall()
        ipa_uk_map = {r[0]: r[1] for r in word_rows}
        ipa_us_map = {r[0]: r[2] for r in word_rows}
        ipa_map = {r[0]: (r[1] or r[2]) for r in word_rows}

        # 2. Fetch definitions
        defs_rows = conn.execute(f"""
            SELECT word_id, definition_en, definition_vi FROM definitions WHERE word_id IN ({id_set_str})
        """).fetchall()
        defs_map: Dict[int, List[Tuple[str, str]]] = {}
        for wid, d_en, d_vi in defs_rows:
            defs_map.setdefault(wid, []).append((d_en or "", d_vi or ""))

        # 3. Fetch linked sentence count
        sent_rows = conn.execute(f"""
            SELECT word_id, count(sentence_id) FROM word_sentences WHERE word_id IN ({id_set_str}) GROUP BY word_id
        """).fetchall()
        sent_counts = {r[0]: r[1] for r in sent_rows}

        # 4. Fetch topics
        topic_rows = conn.execute(f"""
            SELECT word_id, topic FROM word_topics WHERE word_id IN ({id_set_str})
        """).fetchall()
        topic_map = {r[0]: r[1] for r in topic_rows if r[1]}

        enriched_entries: List[Dict[str, Any]] = []
        gate_results: List[QualityGateResult] = []

        passed_all_count = 0
        has_def_en_count = 0
        has_def_vi_count = 0
        has_ipa_count = 0
        has_sent_count = 0
        has_topic_count = 0

        for w in selected_words:
            wid = w.id
            defs = defs_map.get(wid, [])
            has_def_en = any(len(d[0].strip()) >= 5 for d in defs)
            has_def_vi = any(self.vi_validator.validate(d[1]) for d in defs)
            has_ipa = bool(ipa_map.get(wid) and str(ipa_map[wid]).strip())
            has_sent = sent_counts.get(wid, 0) > 0
            has_topic = wid in topic_map

            missing = []
            if not has_def_en:
                missing.append("def_en")
            if not has_def_vi:
                missing.append("def_vi")
            if not has_ipa:
                missing.append("ipa")
            if not has_sent:
                missing.append("sentence")
            if not has_topic:
                missing.append("topic")

            passed_all = len(missing) == 0
            if passed_all:
                passed_all_count += 1
            if has_def_en:
                has_def_en_count += 1
            if has_def_vi:
                has_def_vi_count += 1
            if has_ipa:
                has_ipa_count += 1
            if has_sent:
                has_sent_count += 1
            if has_topic:
                has_topic_count += 1

            gate_res = QualityGateResult(
                word_id=wid,
                lemma=w.lemma,
                has_def_en=has_def_en,
                has_def_vi=has_def_vi,
                has_ipa=has_ipa,
                has_sentence=has_sent,
                has_topic=has_topic,
                passed_all=passed_all,
                missing_fields=missing,
            )
            gate_results.append(gate_res)

            enriched_entries.append({
                "id": wid,
                "lemma": w.lemma,
                "pos": w.pos,
                "ipa_uk": ipa_uk_map.get(wid) or ipa_map.get(wid),
                "ipa_us": ipa_us_map.get(wid) or ipa_map.get(wid),
                "frequency_rank": w.frequency_rank,
                "cefr_level": w.cefr_level,
                "source": w.source,
                "topic": topic_map.get(wid, "General & Everyday"),
                "passed_quality_gates": passed_all,
            })

        total = len(selected_words)
        summary = EnrichmentSummary(
            total_words=total,
            passed_all_gates=passed_all_count,
            def_en_coverage=round(has_def_en_count / total, 4) if total else 0.0,
            def_vi_coverage=round(has_def_vi_count / total, 4) if total else 0.0,
            ipa_coverage=round(has_ipa_count / total, 4) if total else 0.0,
            sentence_coverage=round(has_sent_count / total, 4) if total else 0.0,
            topic_coverage=round(has_topic_count / total, 4) if total else 0.0,
            gate_results=gate_results,
        )

        logger.info(
            "Quality Gates Audit: %d/%d (%.1f%%) passed all gates",
            passed_all_count,
            total,
            (passed_all_count / total * 100) if total else 0.0,
        )
        return enriched_entries, summary
