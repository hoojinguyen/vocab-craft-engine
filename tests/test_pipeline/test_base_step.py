from pathlib import Path
from unittest.mock import MagicMock
import pytest
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.result import StepResult, StepStatus


class ConcreteStep(BaseStep):
    name = "test_step"
    description = "A test step"
    depends_on = ["schema_init"]
    produces = ["words"]
    optional = False
    execution_type = "cpu"

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=10)


class OptionalStep(BaseStep):
    name = "optional_step"
    description = "An optional step"
    depends_on = ["test_step"]
    produces = ["audio_files"]
    optional = True
    execution_type = "io"

    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS, items_processed=5)


def test_base_step_has_depends_on():
    step = ConcreteStep()
    assert step.depends_on == ["schema_init"]


def test_base_step_has_produces():
    step = ConcreteStep()
    assert step.produces == ["words"]


def test_base_step_optional_default_false():
    step = ConcreteStep()
    assert step.optional is False


def test_optional_step_flag():
    step = OptionalStep()
    assert step.optional is True


def test_execution_type():
    assert ConcreteStep().execution_type == "cpu"
    assert OptionalStep().execution_type == "io"


def test_compute_source_hash_empty():
    step = ConcreteStep()
    step.source_files = []
    hash1 = step.compute_source_hash()
    assert isinstance(hash1, str)
    assert len(hash1) == 16  # truncated SHA256


def test_compute_source_hash_with_files(tmp_path):
    test_file = tmp_path / "test.json"
    test_file.write_text("test content")
    step = ConcreteStep()
    step.source_files = [test_file]
    hash1 = step.compute_source_hash()
    assert isinstance(hash1, str)
    assert len(hash1) == 16


def test_compute_source_hash_changes_with_content(tmp_path):
    test_file = tmp_path / "test.json"
    test_file.write_text("content v1")
    step = ConcreteStep()
    step.source_files = [test_file]
    hash1 = step.compute_source_hash()

    test_file.write_text("content v2 with more data")  # size changes
    hash2 = step.compute_source_hash()
    assert hash1 != hash2


def test_rollback_is_noop_by_default():
    step = ConcreteStep()
    ctx = MagicMock()
    step.rollback(ctx)  # should not raise
