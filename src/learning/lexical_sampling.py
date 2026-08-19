"""Deterministic, auditable sampling of lexical definition inputs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from src.learning.models import canonical_json
from src.learning.store import LearningGraphStore


@dataclass(frozen=True)
class PilotRow:
    input_id: str
    frequency_rank: int
    source_word_id: int
    source_definition_id: int
    input_key: str
    rank_band: str
    source_asset_id: str
    pos: str

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "input_id": self.input_id,
            "frequency_rank": self.frequency_rank,
            "source_word_id": self.source_word_id,
            "source_definition_id": self.source_definition_id,
            "input_key": self.input_key,
        }


@dataclass(frozen=True)
class PilotSelection:
    seed: str
    rows: tuple[PilotRow, ...]
    inventory_sha256: str
    stratum_counts: dict[str, int]

    @property
    def input_ids(self) -> tuple[str, ...]:
        return tuple(row.input_id for row in self.rows)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "kind": "stratified_pilot_v1",
            "seed": self.seed,
            "input_ids": list(self.input_ids),
            "inventory_sha256": self.inventory_sha256,
            "stratum_counts": dict(self.stratum_counts),
        }


class LexicalPilotSampler:
    """Select a stable rank/source/POS-stratified lexical inventory."""

    def __init__(self, store: LearningGraphStore):
        self.store = store

    def select(self, snapshot_id: str, size: int, seed: str) -> PilotSelection:
        if size <= 0:
            raise ValueError("sample size must be positive")
        records = self._rows(snapshot_id)
        if size > len(records):
            raise ValueError(
                f"requested sample size {size} but snapshot contains only {len(records)} inputs"
            )
        grouped: dict[tuple[str, str, str], list[PilotRow]] = {}
        for row in records:
            key = (row.rank_band, row.source_asset_id, row.pos)
            grouped.setdefault(key, []).append(row)
        strata = sorted(grouped)
        if size < len(strata):
            raise ValueError(
                f"sample size {size} is smaller than {len(strata)} nonempty strata"
            )
        for key in strata:
            grouped[key].sort(key=lambda row: self._candidate_key(seed, row.input_id))

        quotas = {key: 1 for key in strata}
        remaining = size - len(strata)
        while remaining:
            available = {
                key: len(grouped[key]) - quotas[key]
                for key in strata
                if quotas[key] < len(grouped[key])
            }
            if not available:
                break
            total_population = sum(available.values())
            allocation = {key: 0 for key in available}
            fractional: list[tuple[float, tuple[str, str, str]]] = []
            for key, population in available.items():
                ideal = remaining * population / total_population
                extra = min(population, int(ideal))
                allocation[key] = extra
                fractional.append((ideal - int(ideal), key))
            assigned = sum(allocation.values())
            leftover = remaining - assigned
            for _, key in sorted(fractional, key=lambda item: (-item[0], item[1])):
                if leftover == 0:
                    break
                if allocation[key] < available[key]:
                    allocation[key] += 1
                    leftover -= 1
            for key, extra in allocation.items():
                quotas[key] += extra
            remaining = leftover

        chosen = [row for key in strata for row in grouped[key][: quotas[key]]]
        chosen.sort(
            key=lambda row: (
                row.frequency_rank,
                row.source_word_id,
                row.source_definition_id,
                row.input_key,
            )
        )
        ordered_identities = [row.identity for row in chosen]
        inventory_sha256 = hashlib.sha256(
            canonical_json(ordered_identities).encode("utf-8")
        ).hexdigest()
        counts = {self._stratum_name(key): quotas[key] for key in strata if quotas[key]}
        return PilotSelection(seed, tuple(chosen), inventory_sha256, counts)

    def _rows(self, snapshot_id: str) -> list[PilotRow]:
        rows = (
            self.store.connection()
            .execute(
                """
            SELECT input.input_id, input.frequency_rank, input.source_word_id,
                   input.source_definition_id, input.input_key,
                   snapshot.asset_id, input.pos
            FROM lexical_definition_inputs AS input
            JOIN source_snapshots AS snapshot
              ON snapshot.snapshot_id = input.snapshot_id
            WHERE input.snapshot_id = ?
              AND input.frequency_rank BETWEEN 1 AND 3500
            """,
                [snapshot_id],
            )
            .fetchall()
        )
        return [
            PilotRow(
                input_id=row[0],
                frequency_rank=row[1],
                source_word_id=row[2],
                source_definition_id=row[3],
                input_key=row[4],
                rank_band=self._rank_band(row[1]),
                source_asset_id=row[5],
                pos=row[6],
            )
            for row in rows
        ]

    @staticmethod
    def _rank_band(rank: int) -> str:
        if rank <= 500:
            return "1-500"
        if rank <= 1500:
            return "501-1500"
        if rank <= 2500:
            return "1501-2500"
        return "2501-3500"

    @staticmethod
    def _candidate_key(seed: str, input_id: str) -> str:
        return hashlib.sha256(f"{seed}:{input_id}".encode()).hexdigest()

    @staticmethod
    def _stratum_name(key: tuple[str, str, str]) -> str:
        return "|".join(key)
