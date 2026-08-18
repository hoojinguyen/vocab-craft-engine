from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.learning.quality import QualityGate
from src.learning.repository import ContentRepository


@dataclass(frozen=True)
class LexicalPack:
    pack_id: str
    version: str
    validation_run_id: str
    cefr_level: str
    senses: tuple[dict[str, object], ...]
    examples: tuple[dict[str, object], ...]
    source_attributions: tuple[dict[str, object], ...]
    quality_report: dict[str, object]


class LexicalPackComposer:
    """Select only approved, gate-passing lexical senses for offline export."""

    def __init__(
        self, repository: ContentRepository, quality_gate: QualityGate | None = None
    ) -> None:
        self.repository = repository
        self.quality_gate = quality_gate or QualityGate()

    def compose(
        self,
        validation_run_id: str,
        pack_id: str,
        version: str,
        cefr_level: str,
    ) -> LexicalPack:
        run = (
            self.repository.store.connection()
            .execute(
                "SELECT validation_run_id FROM validation_runs WHERE validation_run_id = ?",
                [validation_run_id],
            )
            .fetchone()
        )
        if run is None:
            raise ValueError(f"validation run does not exist: {validation_run_id!r}")
        rows = (
            self.repository.store.connection()
            .execute(
                """
            SELECT revision.revision_id, revision.content_id, revision.revision_number,
                   revision.payload_json, revision.payload_sha256,
                   content.stable_key, content.content_type,
                   candidate.candidate_id, candidate.state, raw.asset_id,
                   source.title, source.license_id, source.license_url,
                   source.attribution, source.sha256
            FROM content_revisions AS revision
            JOIN canonical_content AS content ON content.content_id = revision.content_id
            JOIN content_candidates AS candidate
              ON candidate.candidate_id = revision.source_candidate_id
            JOIN raw_reference_records AS raw ON raw.raw_record_id = candidate.raw_record_id
            JOIN source_assets AS source ON source.asset_id = raw.asset_id
            WHERE revision.review_state = 'approved'
              AND content.content_type = 'sense'
              AND candidate.state = 'approved'
              AND EXISTS (
                  SELECT 1 FROM candidate_gate_results AS gate
                  WHERE gate.validation_run_id = ?
                    AND gate.candidate_id = candidate.candidate_id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM candidate_gate_results AS gate
                  WHERE gate.validation_run_id = ?
                    AND gate.candidate_id = candidate.candidate_id
                    AND NOT gate.passed
              )
            ORDER BY revision.revision_id
            """,
                [validation_run_id, validation_run_id],
            )
            .fetchall()
        )

        selected: list[dict[str, Any]] = []
        attributions: dict[str, dict[str, object]] = {}
        for row in rows:
            payload = json.loads(str(row[3]))
            if payload.get("cefr_level") != cefr_level:
                continue
            self._require_publishable_payload(payload)
            report = self.quality_gate.validate_payload("sense", payload, str(row[0]))
            if not report.passed:
                raise ValueError("selected lexical sense failed quality gates")
            source_asset_id = str(row[9])
            selected.append(
                {
                    "sense_id": str(row[0]),
                    "stable_key": str(row[5]),
                    "lemma": str(payload["lemma"]),
                    "pos": str(payload["pos"]),
                    "definition_en": str(payload["definition_en"]),
                    "definition_vi": str(payload["definition_vi"]),
                    "frequency_rank": int(payload["frequency_rank"]),
                    "cefr_level": str(payload["cefr_level"]),
                    "ipa_uk": payload.get("ipa_uk"),
                    "ipa_us": payload.get("ipa_us"),
                    "source_asset_id": source_asset_id,
                    "examples": list(payload["examples"]),
                }
            )
            attributions[source_asset_id] = {
                "asset_id": source_asset_id,
                "title": str(row[10]),
                "license_id": str(row[11]),
                "license_url": str(row[12]),
                "attribution": str(row[13]),
                "sha256": str(row[14]),
            }

        if not selected:
            raise ValueError("lexical pack selection is empty")
        counts: dict[str, int] = {}
        for sense in selected:
            source_asset_id = str(sense["source_asset_id"])
            counts[source_asset_id] = counts.get(source_asset_id, 0) + 1
        underfilled = [asset_id for asset_id, count in counts.items() if count < 30]
        if underfilled:
            raise ValueError("each source asset requires at least 30 approved senses")

        selected.sort(
            key=lambda sense: (
                int(sense["frequency_rank"]),
                str(sense["lemma"]),
                str(sense["pos"]),
                str(sense["stable_key"]),
            )
        )
        examples: list[dict[str, object]] = []
        for sense in selected:
            for rank, example in enumerate(sense.pop("examples", []), start=1):
                examples.append(
                    {
                        "sense_id": sense["sense_id"],
                        "rank": rank,
                        "text_en": example.get("text_en"),
                        "text_vi": example.get("text_vi"),
                        "source": example.get("source"),
                    }
                )
        examples.sort(
            key=lambda example: (
                str(example["sense_id"]),
                int(example["rank"]),
                str(example["text_en"]),
            )
        )
        return LexicalPack(
            pack_id=pack_id,
            version=version,
            validation_run_id=validation_run_id,
            cefr_level=cefr_level,
            senses=tuple(selected),
            examples=tuple(examples),
            source_attributions=tuple(
                attributions[key] for key in sorted(attributions)
            ),
            quality_report={
                "passed": True,
                "approved_sense_count": len(selected),
                "cefr_level": cefr_level,
                "source_counts": dict(sorted(counts.items())),
            },
        )

    @staticmethod
    def _require_publishable_payload(payload: dict[str, Any]) -> None:
        required = ("definition_en", "definition_vi", "frequency_rank", "examples")
        if any(not payload.get(key) for key in required):
            raise ValueError("selected lexical sense is incomplete")
        if not (payload.get("ipa_uk") or payload.get("ipa_us")):
            raise ValueError("selected lexical sense is missing IPA")
