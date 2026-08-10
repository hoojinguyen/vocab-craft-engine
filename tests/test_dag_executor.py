"""Tests for DAGExecutor."""

import time
import pytest
from typing import Set

from src.pipeline.context import PipelineContext
from src.pipeline.dag import DAGExecutor, PipelineStep
from src.pipeline.registry import CheckpointRegistry


def test_dag_executes_in_dependency_order():
    """Steps execute only after their dependencies complete."""
    execution_order = []
    ctx = PipelineContext()

    def make_step(name: str):
        def step(context: PipelineContext):
            execution_order.append(name)
        return step

    dag = DAGExecutor()
    dag.add_step("c", make_step("c"), depends={"a", "b"})
    dag.add_step("b", make_step("b"), depends={"a"})
    dag.add_step("a", make_step("a"))

    dag.execute(ctx)

    assert execution_order.index("a") < execution_order.index("b")
    assert execution_order.index("b") < execution_order.index("c")


def test_dag_parallelizes_independent_steps():
    """Independent steps run concurrently."""
    ctx = PipelineContext()
    start_times = {}
    end_times = {}

    def slow_step(name: str, delay: float):
        def step(context: PipelineContext):
            start_times[name] = time.time()
            time.sleep(delay)
            end_times[name] = time.time()
        return step

    dag = DAGExecutor()
    dag.add_step("x", slow_step("x", 0.3))
    dag.add_step("y", slow_step("y", 0.3))

    dag.execute(ctx)

    assert abs(start_times["x"] - start_times["y"]) < 0.1


def test_dag_respects_checkpoints():
    """Completed stages are skipped unless force_reset."""
    ctx = PipelineContext()
    call_count = {"a": 0}

    def counting_step(name: str):
        def step(context: PipelineContext):
            call_count[name] += 1
        return step

    dag = DAGExecutor(registry=CheckpointRegistry(ctx.checkpoint_dir))
    dag.add_step("done_step", counting_step("done_step"))
    dag.add_step("after", counting_step("a"), depends={"done_step"})

    dag.registry.mark_done("done_step")

    dag.execute(ctx, force_reset=False)

    assert call_count.get("done_step", 0) == 0
    assert call_count["a"] == 1


def test_dag_force_reset_reruns_completed():
    """force_reset=True re-runs all steps."""
    ctx = PipelineContext()
    call_count = {"step": 0}

    def step_fn(context: PipelineContext):
        call_count["step"] += 1

    dag = DAGExecutor(registry=CheckpointRegistry(ctx.checkpoint_dir))
    dag.add_step("step", step_fn)
    dag.registry.mark_done("step")

    dag.execute(ctx, force_reset=True)

    assert call_count["step"] == 1
