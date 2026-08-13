"""
State Manager V2 for Pipeline.

DuckDB-backed state manager enforcing content-hash caching, force overrides,
and cascade invalidation of downstream steps.
"""

import logging
from typing import Set, Tuple

from src.db.duckdb_manager import DuckDBManager
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.dag import DAG

logger = logging.getLogger(__name__)


class StateManager:
    """Manages step execution state, caching, and invalidation."""

    def __init__(self, db_manager: DuckDBManager):
        self.db_manager = db_manager

    def should_skip(
        self,
        step: BaseStep,
        dag: DAG,
        force_steps: Set[str] = set(),
        force_all: bool = False,
    ) -> Tuple[bool, str]:
        """Determines if a step can be skipped using DuckDB metadata and source hash."""
        if force_all:
            return False, "Force all specified"

        if step.name in force_steps:
            return False, f"Force step '{step.name}' specified"

        # Check upstream dependencies
        for dep_name in step.depends_on:
            dep_meta = self.db_manager.get_step_meta(dep_name)
            if dep_meta is None or dep_meta.get("status") != "success":
                return False, f"Upstream dependency '{dep_name}' not successful or invalidated"

        # Check step's own source hash and previous status
        meta = self.db_manager.get_step_meta(step.name)
        if meta is None:
            return False, "No previous run record"

        if meta.get("status") != "success":
            return False, f"Previous run status was '{meta.get('status')}'"

        current_hash = step.compute_source_hash()
        if meta.get("source_hash") != current_hash:
            return False, f"Source hash changed"

        return True, "Cached (source hash matches)"

    def record_success(
        self, step_name: str, source_hash: str, row_count: int, duration_secs: float
    ) -> None:
        """Records successful step execution in DuckDB meta."""
        self.db_manager.save_step_meta(
            step_name=step_name,
            status="success",
            source_hash=source_hash,
            row_count=row_count,
            duration_secs=duration_secs,
            error_message=None,
        )

    def record_failure(
        self, step_name: str, source_hash: str, duration_secs: float, error_msg: str
    ) -> None:
        """Records failed step execution in DuckDB meta."""
        self.db_manager.save_step_meta(
            step_name=step_name,
            status="failed",
            source_hash=source_hash,
            row_count=0,
            duration_secs=duration_secs,
            error_message=error_msg,
        )

    def invalidate_step(self, step_name: str, dag: DAG) -> None:
        """Invalidates step_name and all downstream dependents in DuckDB meta."""
        to_invalidate = {step_name} | dag.get_downstream(step_name)
        for name in to_invalidate:
            meta = self.db_manager.get_step_meta(name)
            curr_hash = meta.get("source_hash") if meta else ""
            self.db_manager.save_step_meta(
                step_name=name,
                status="invalidated",
                source_hash=curr_hash,
                row_count=0,
                duration_secs=0.0,
                error_message="Invalidated by upstream change",
            )
        logger.info("Invalidated steps: %s", to_invalidate)

    def clear_state(self) -> None:
        """Clears all pipeline metadata and checkpoints."""
        conn = self.db_manager.get_connection()
        conn.execute("DELETE FROM _pipeline_meta")
        conn.execute("DELETE FROM _batch_checkpoints")
