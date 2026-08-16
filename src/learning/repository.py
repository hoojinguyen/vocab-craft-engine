from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from src.learning.models import ContentRevisionInput, ReviewState, canonical_json
from src.learning.store import LearningGraphStore

_REVIEW_DECISIONS = {
    ReviewState.APPROVED.value,
    ReviewState.REJECTED.value,
    ReviewState.QUARANTINED.value,
}


class ContentRepository:
    """Persist candidate content and its immutable reviewed graph revisions."""

    def __init__(self, store: LearningGraphStore):
        self.store = store

    def create_candidate(
        self,
        raw_record_id: str,
        content_type: str,
        payload: dict[str, Any],
        evidence: dict[str, Any],
        confidence: float,
    ) -> str:
        evidence_json = canonical_json(evidence)
        candidate_id = str(uuid4())

        with self.store.transaction() as connection:
            raw_record = connection.execute(
                """
                SELECT raw.raw_record_id
                FROM raw_reference_records AS raw
                JOIN source_assets AS source ON source.asset_id = raw.asset_id
                WHERE raw.raw_record_id = ? AND source.validation_status = ?
                """,
                [raw_record_id, ReviewState.APPROVED.value],
            ).fetchone()
            if raw_record is None:
                raise ValueError("raw record is missing or source is not approved")
            revision_input = self._revision_input_from_payload(
                content_type, payload, "candidate"
            )

            connection.execute(
                """
                INSERT INTO content_candidates (
                    candidate_id, raw_record_id, content_type, normalized_payload_json,
                    evidence_json, confidence
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    candidate_id,
                    raw_record_id,
                    content_type,
                    canonical_json(revision_input.payload),
                    evidence_json,
                    confidence,
                ],
            )
        return candidate_id

    def review_candidate(
        self, candidate_id: str, decision: str, reviewer_id: str, rationale: str
    ) -> str | None:
        self._validate_decision(decision)
        with self.store.transaction() as connection:
            candidate = connection.execute(
                """
                SELECT content_type, normalized_payload_json, state
                FROM content_candidates WHERE candidate_id = ?
                """,
                [candidate_id],
            ).fetchone()
            if candidate is None:
                raise ValueError(f"candidate {candidate_id!r} does not exist")
            content_type, payload_json, state = candidate
            if state != ReviewState.CANDIDATE.value:
                raise ValueError(
                    f"candidate {candidate_id!r} has already been reviewed"
                )

            review_id = str(uuid4())
            if decision != ReviewState.APPROVED.value:
                connection.execute(
                    """
                    INSERT INTO content_reviews (
                        review_id, candidate_id, decision, reviewer_id, rationale
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [review_id, candidate_id, decision, reviewer_id, rationale],
                )
                connection.execute(
                    "UPDATE content_candidates SET state = ? WHERE candidate_id = ?",
                    [decision, candidate_id],
                )
                return None

            revision_input = self._revision_input(content_type, payload_json)
            content_id = self._content_id_for_stable_key(
                connection, revision_input.stable_key, revision_input.content_type.value
            )
            revision_number = self._next_revision_number(connection, content_id)
            revision_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO content_revisions (
                    revision_id, content_id, revision_number, payload_json,
                    payload_sha256, review_state, source_candidate_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    revision_id,
                    content_id,
                    revision_number,
                    canonical_json(revision_input.payload),
                    revision_input.payload_sha256,
                    ReviewState.APPROVED.value,
                    candidate_id,
                ],
            )
            connection.execute(
                """
                INSERT INTO content_reviews (
                    review_id, candidate_id, revision_id, decision, reviewer_id, rationale
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    review_id,
                    candidate_id,
                    revision_id,
                    decision,
                    reviewer_id,
                    rationale,
                ],
            )
            connection.execute(
                "UPDATE content_candidates SET state = ? WHERE candidate_id = ?",
                [ReviewState.APPROVED.value, candidate_id],
            )
            return revision_id

    def create_revision(
        self,
        prior_revision_id: str,
        payload: dict[str, Any],
        reviewer_id: str,
        rationale: str,
    ) -> str:
        with self.store.transaction() as connection:
            prior_revision = connection.execute(
                """
                SELECT revision.content_id, revision.source_candidate_id,
                       content.stable_key, content.content_type, revision.review_state
                FROM content_revisions AS revision
                JOIN canonical_content AS content ON content.content_id = revision.content_id
                WHERE revision.revision_id = ?
                """,
                [prior_revision_id],
            ).fetchone()
            if prior_revision is None:
                raise ValueError(f"revision {prior_revision_id!r} does not exist")
            (
                content_id,
                candidate_id,
                stable_key,
                content_type,
                review_state,
            ) = prior_revision
            if review_state != ReviewState.APPROVED.value:
                raise ValueError("a new revision requires an approved prior revision")

            revision_input = self._revision_input_from_payload(
                content_type, payload, "revision"
            )
            if revision_input.stable_key != stable_key:
                raise ValueError("revision stable_key must match canonical content")

            revision_id = str(uuid4())
            revision_number = self._next_revision_number(connection, content_id)
            connection.execute(
                """
                INSERT INTO content_revisions (
                    revision_id, content_id, revision_number, payload_json,
                    payload_sha256, review_state, source_candidate_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    revision_id,
                    content_id,
                    revision_number,
                    canonical_json(revision_input.payload),
                    revision_input.payload_sha256,
                    ReviewState.APPROVED.value,
                    candidate_id,
                ],
            )
            connection.execute(
                """
                INSERT INTO content_reviews (
                    review_id, candidate_id, revision_id, decision, reviewer_id, rationale
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid4()),
                    candidate_id,
                    revision_id,
                    ReviewState.APPROVED.value,
                    reviewer_id,
                    rationale,
                ],
            )
            return revision_id

    def add_edge(
        self,
        from_revision_id: str,
        to_revision_id: str,
        relation_type: str,
        attributes: dict[str, Any] | None = None,
    ) -> str:
        if from_revision_id == to_revision_id:
            raise ValueError("content edges cannot be self-links")
        attributes_json = canonical_json(attributes or {})
        edge_id = str(uuid4())

        with self.store.transaction() as connection:
            approved_count = connection.execute(
                """
                SELECT count(*) FROM content_revisions
                WHERE revision_id IN (?, ?) AND review_state = ?
                """,
                [from_revision_id, to_revision_id, ReviewState.APPROVED.value],
            ).fetchone()[0]
            if approved_count != 2:
                raise ValueError("content edges require approved revision endpoints")
            connection.execute(
                """
                INSERT INTO content_edges (
                    edge_id, from_revision_id, to_revision_id, relation_type, attributes_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    edge_id,
                    from_revision_id,
                    to_revision_id,
                    relation_type,
                    attributes_json,
                ],
            )
        return edge_id

    def get_revision(self, revision_id: str) -> dict[str, object]:
        row = (
            self.store.connection()
            .execute(
                """
            SELECT revision.revision_id, revision.content_id, revision.revision_number,
                   revision.payload_json, revision.payload_sha256, revision.review_state,
                   revision.source_candidate_id, revision.created_at, content.stable_key,
                   content.content_type
            FROM content_revisions AS revision
            JOIN canonical_content AS content ON content.content_id = revision.content_id
            WHERE revision.revision_id = ?
            """,
                [revision_id],
            )
            .fetchone()
        )
        if row is None:
            raise ValueError(f"revision {revision_id!r} does not exist")
        columns = (
            "revision_id",
            "content_id",
            "revision_number",
            "payload_json",
            "payload_sha256",
            "review_state",
            "source_candidate_id",
            "created_at",
            "stable_key",
            "content_type",
        )
        return dict(zip(columns, row, strict=True))

    def get_latest_approved_revision(self, stable_key: str) -> str:
        revision = self.store.fetch_value(
            """
            SELECT revision.revision_id
            FROM content_revisions AS revision
            JOIN canonical_content AS content ON content.content_id = revision.content_id
            WHERE content.stable_key = ? AND revision.review_state = ?
            ORDER BY revision.revision_number DESC
            LIMIT 1
            """,
            [stable_key, ReviewState.APPROVED.value],
        )
        if revision is None:
            raise ValueError(f"no approved revision for {stable_key}")
        return str(revision)

    @staticmethod
    def _validate_decision(decision: str) -> None:
        if decision not in _REVIEW_DECISIONS:
            raise ValueError(f"unsupported review decision: {decision}")

    @staticmethod
    def _revision_input(content_type: str, payload_json: str) -> ContentRevisionInput:
        payload = json.loads(payload_json)
        return ContentRepository._revision_input_from_payload(
            content_type, payload, "approved candidate"
        )

    @staticmethod
    def _revision_input_from_payload(
        content_type: str, payload: dict[str, Any], subject: str
    ) -> ContentRevisionInput:
        try:
            stable_key = payload["stable_key"]
        except KeyError as exc:
            raise ValueError(f"{subject} payload requires stable_key") from exc
        return ContentRevisionInput(
            stable_key=stable_key,
            content_type=content_type,
            payload=payload,
        )

    @staticmethod
    def _next_revision_number(connection: Any, content_id: str) -> int:
        current = connection.execute(
            "SELECT coalesce(max(revision_number), 0) FROM content_revisions WHERE content_id = ?",
            [content_id],
        ).fetchone()[0]
        return int(current) + 1

    @staticmethod
    def _content_id_for_stable_key(
        connection: Any, stable_key: str, content_type: str
    ) -> str:
        existing = connection.execute(
            "SELECT content_id, content_type FROM canonical_content WHERE stable_key = ?",
            [stable_key],
        ).fetchone()
        if existing is not None:
            content_id, existing_type = existing
            if existing_type != content_type:
                raise ValueError("canonical stable_key cannot change content type")
            return str(content_id)

        content_id = str(uuid4())
        connection.execute(
            """
            INSERT INTO canonical_content (content_id, stable_key, content_type)
            VALUES (?, ?, ?)
            """,
            [content_id, stable_key, content_type],
        )
        return content_id
