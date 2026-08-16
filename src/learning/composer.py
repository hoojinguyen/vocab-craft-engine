from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from src.learning.quality import QualityGate
from src.learning.repository import ContentRepository


@dataclass(frozen=True)
class PackGraph:
    pack_id: str
    version: str
    root_module_revision_id: str
    revisions: Sequence[dict[str, object]]
    edges: Sequence[dict[str, object]]
    quality_report: dict[str, object]
    ordering: dict[str, tuple[int, str, str]]
    source_attributions: Sequence[dict[str, object]]

    @property
    def revision_ids(self) -> tuple[str, ...]:
        return tuple(str(item["revision_id"]) for item in self.revisions)

    def order_key(self, revision_id: str) -> tuple[int, str, str]:
        return self.ordering[revision_id]


class CurriculumComposer:
    """Build deterministic, review-gated curriculum packs from a graph module root."""

    _TRAVERSAL_RELATIONS: ClassVar[frozenset[str]] = frozenset(
        {
            "module_objective",
            "prerequisite",
            "objective_sense",
            "objective_chunk",
            "objective_pattern",
            "objective_sentence",
            "objective_scenario",
            "scenario_turn",
            "response_path",
            "objective_assessment",
            "objective_activity",
            "activity_template",
            "activity_assessment",
        }
    )
    _COVERAGE_CONTENT_RELATIONS: ClassVar[frozenset[str]] = frozenset(
        {
            "objective_sense",
            "objective_chunk",
            "objective_pattern",
        }
    )

    def __init__(
        self,
        repository: ContentRepository,
        quality_gate: QualityGate | None = None,
    ) -> None:
        self.repository = repository
        self.quality_gate = quality_gate or QualityGate()

    def compose(self, module_revision_id: str, pack_id: str, version: str) -> PackGraph:
        revisions_by_id, edges = self._load_approved_graph()
        root = revisions_by_id.get(module_revision_id)
        if root is None or root["content_type"] != "module":
            raise ValueError("module revision must be approved")

        reachable_ids, reachable_edges = self._reachable_graph(
            module_revision_id, revisions_by_id, edges
        )
        revisions = [revisions_by_id[revision_id] for revision_id in reachable_ids]
        self._validate_coverage(revisions, reachable_edges)
        quality_input = [
            {
                "revision_id": revision["revision_id"],
                "content_type": revision["content_type"],
                "review_state": revision["review_state"],
                "payload": revision["payload"],
                "source_asset_id": revision["source_asset_id"],
            }
            for revision in revisions
        ]
        quality_edges = [
            {
                "from_revision_id": edge["from_revision_id"],
                "to_revision_id": edge["to_revision_id"],
                "relation_type": edge["relation_type"],
                "attributes": edge["attributes"],
            }
            for edge in reachable_edges
        ]
        report = self.quality_gate.validate_graph(quality_input, quality_edges)
        quality_report: dict[str, object] = {
            "passed": report.passed,
            "failures": [asdict(failure) for failure in report.failures],
            **self.quality_gate.summarize(quality_input),
        }
        if not report.passed:
            raise ValueError("quality gates failed")

        ordering = self._ordering(revisions_by_id, reachable_ids, reachable_edges)
        ordered_revisions = tuple(
            sorted(
                (
                    self._public_revision(revisions_by_id[revision_id])
                    for revision_id in reachable_ids
                ),
                key=lambda revision: ordering[str(revision["revision_id"])],
            )
        )
        ordered_edges = tuple(
            sorted(
                (self._public_edge(edge) for edge in reachable_edges),
                key=lambda edge: (
                    str(edge["relation_type"]),
                    str(edge["from_revision_id"]),
                    str(edge["to_revision_id"]),
                ),
            )
        )
        return PackGraph(
            pack_id=pack_id,
            version=version,
            root_module_revision_id=module_revision_id,
            revisions=ordered_revisions,
            edges=ordered_edges,
            quality_report=quality_report,
            ordering=ordering,
            source_attributions=self._source_attributions(
                revisions_by_id, reachable_ids
            ),
        )

    def _load_approved_graph(
        self,
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        connection = self.repository.store.connection()
        rows = connection.execute("""
            SELECT revision.revision_id, revision.content_id, revision.revision_number,
                   revision.payload_json, revision.payload_sha256, revision.review_state,
                   revision.source_candidate_id, content.stable_key, content.content_type,
                   source.asset_id, source.title, source.license_id, source.license_url,
                   source.attribution, source.sha256
            FROM content_revisions AS revision
            JOIN canonical_content AS content ON content.content_id = revision.content_id
            JOIN content_candidates AS candidate
              ON candidate.candidate_id = revision.source_candidate_id
            JOIN raw_reference_records AS raw ON raw.raw_record_id = candidate.raw_record_id
            JOIN source_assets AS source ON source.asset_id = raw.asset_id
            WHERE revision.review_state = 'approved'
            """).fetchall()
        revisions_by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            (
                revision_id,
                content_id,
                revision_number,
                payload_json,
                payload_sha256,
                review_state,
                source_candidate_id,
                stable_key,
                content_type,
                asset_id,
                title,
                license_id,
                license_url,
                attribution,
                source_sha256,
            ) = row
            revisions_by_id[str(revision_id)] = {
                "revision_id": str(revision_id),
                "content_id": str(content_id),
                "revision_number": int(revision_number),
                "payload_json": str(payload_json),
                "payload_sha256": str(payload_sha256),
                "review_state": str(review_state),
                "source_candidate_id": str(source_candidate_id),
                "stable_key": str(stable_key),
                "content_type": str(content_type),
                "payload": json.loads(payload_json),
                "source_asset_id": str(asset_id),
                "source_attribution": {
                    "asset_id": str(asset_id),
                    "title": str(title),
                    "license_id": str(license_id),
                    "license_url": str(license_url),
                    "attribution": str(attribution),
                    "sha256": str(source_sha256),
                },
            }
        edge_rows = connection.execute("""
            SELECT edge_id, from_revision_id, to_revision_id, relation_type, attributes_json
            FROM content_edges
            """).fetchall()
        edges = [
            {
                "edge_id": str(edge_id),
                "from_revision_id": str(from_revision_id),
                "to_revision_id": str(to_revision_id),
                "relation_type": str(relation_type),
                "attributes_json": str(attributes_json),
                "attributes": json.loads(attributes_json),
            }
            for edge_id, from_revision_id, to_revision_id, relation_type, attributes_json in edge_rows
        ]
        return revisions_by_id, edges

    def _reachable_graph(
        self,
        root_id: str,
        revisions_by_id: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> tuple[set[str], list[dict[str, Any]]]:
        outgoing: dict[str, list[dict[str, Any]]] = {}
        for edge in edges:
            if edge["relation_type"] not in self._TRAVERSAL_RELATIONS:
                continue
            if edge["from_revision_id"] not in revisions_by_id:
                continue
            if edge["to_revision_id"] not in revisions_by_id:
                continue
            outgoing.setdefault(str(edge["from_revision_id"]), []).append(edge)

        reachable = {root_id}
        pending = [root_id]
        while pending:
            revision_id = pending.pop()
            for edge in outgoing.get(revision_id, []):
                target = str(edge["to_revision_id"])
                if target not in reachable:
                    reachable.add(target)
                    pending.append(target)
        return reachable, [
            edge
            for edge in edges
            if edge["from_revision_id"] in reachable
            and edge["to_revision_id"] in reachable
            and edge["relation_type"] in self._TRAVERSAL_RELATIONS
        ]

    def _validate_coverage(
        self, revisions: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> None:
        revisions_by_id = {
            str(revision["revision_id"]): revision for revision in revisions
        }
        outgoing: dict[str, list[dict[str, Any]]] = {}
        for edge in edges:
            outgoing.setdefault(str(edge["from_revision_id"]), []).append(edge)

        for objective in revisions:
            if objective["content_type"] != "objective":
                continue
            objective_id = str(objective["revision_id"])
            objective_edges = outgoing.get(objective_id, [])
            has_content = any(
                edge["relation_type"] in self._COVERAGE_CONTENT_RELATIONS
                for edge in objective_edges
            )
            has_sentence = any(
                edge["relation_type"] == "objective_sentence"
                for edge in objective_edges
            )
            scenarios = [
                edge["to_revision_id"]
                for edge in objective_edges
                if edge["relation_type"] == "objective_scenario"
                and revisions_by_id.get(str(edge["to_revision_id"]), {}).get(
                    "content_type"
                )
                == "scenario"
            ]
            has_scenario = any(
                any(
                    edge["relation_type"] == "scenario_turn"
                    for edge in outgoing.get(str(scenario), [])
                )
                for scenario in scenarios
            )
            has_assessment = any(
                edge["relation_type"] == "objective_assessment"
                for edge in objective_edges
            )
            activities = [
                str(edge["to_revision_id"])
                for edge in objective_edges
                if edge["relation_type"] == "objective_activity"
                and revisions_by_id.get(str(edge["to_revision_id"]), {}).get(
                    "content_type"
                )
                == "activity"
            ]
            has_assessed_activity = any(
                {edge["relation_type"] for edge in outgoing.get(activity, [])}
                >= {"activity_template", "activity_assessment"}
                for activity in activities
            )
            if not all(
                (
                    has_content,
                    has_sentence,
                    has_scenario,
                    has_assessment,
                    has_assessed_activity,
                )
            ):
                raise ValueError("objective coverage is incomplete")

    def _ordering(
        self,
        revisions_by_id: dict[str, dict[str, Any]],
        reachable_ids: set[str],
        edges: list[dict[str, Any]],
    ) -> dict[str, tuple[int, str, str]]:
        prerequisites: dict[str, list[str]] = {
            revision_id: [] for revision_id in reachable_ids
        }
        for edge in edges:
            if edge["relation_type"] == "prerequisite":
                prerequisites[str(edge["from_revision_id"])].append(
                    str(edge["to_revision_id"])
                )
        status: dict[str, str] = {}
        topological: list[str] = []

        def visit(revision_id: str) -> None:
            if status.get(revision_id) == "visiting":
                raise ValueError("prerequisite cycle")
            if status.get(revision_id) == "visited":
                return
            status[revision_id] = "visiting"
            for target in sorted(
                prerequisites[revision_id], key=self._stable_sort_key(revisions_by_id)
            ):
                visit(target)
            status[revision_id] = "visited"
            topological.append(revision_id)

        for revision_id in sorted(
            reachable_ids, key=self._stable_sort_key(revisions_by_id)
        ):
            visit(revision_id)
        return {
            revision_id: (
                topological.index(revision_id),
                str(revisions_by_id[revision_id]["stable_key"]),
                revision_id,
            )
            for revision_id in reachable_ids
        }

    @staticmethod
    def _stable_sort_key(revisions_by_id: dict[str, dict[str, Any]]):
        return lambda revision_id: (
            str(revisions_by_id[revision_id]["stable_key"]),
            revision_id,
        )

    @staticmethod
    def _public_revision(revision: dict[str, Any]) -> dict[str, object]:
        return {
            key: revision[key]
            for key in (
                "revision_id",
                "content_id",
                "stable_key",
                "content_type",
                "revision_number",
                "payload_json",
                "payload_sha256",
            )
        }

    @staticmethod
    def _public_edge(edge: dict[str, Any]) -> dict[str, object]:
        return {
            key: edge[key]
            for key in (
                "edge_id",
                "from_revision_id",
                "to_revision_id",
                "relation_type",
                "attributes_json",
            )
        }

    @staticmethod
    def _source_attributions(
        revisions_by_id: dict[str, dict[str, Any]], reachable_ids: set[str]
    ) -> tuple[dict[str, object], ...]:
        by_asset = {
            str(revisions_by_id[revision_id]["source_asset_id"]): revisions_by_id[
                revision_id
            ]["source_attribution"]
            for revision_id in reachable_ids
        }
        return tuple(by_asset[asset_id] for asset_id in sorted(by_asset))
