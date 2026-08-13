import pytest
from src.pipeline.core.base_step import BaseStep
from src.pipeline.core.dag import DAG
from src.pipeline.core.result import StepResult, StepStatus


class DummyStep(BaseStep):
    def should_skip(self, ctx):
        return False, ""

    def run(self, ctx):
        return StepResult(step_name=self.name, status=StepStatus.SUCCESS)


class StepA(DummyStep):
    name = "step_a"
    depends_on = []
    produces = ["table_a"]


class StepB(DummyStep):
    name = "step_b"
    depends_on = ["step_a"]
    produces = ["table_b"]


class StepC(DummyStep):
    name = "step_c"
    depends_on = ["step_a"]
    produces = ["table_c"]


class StepD(DummyStep):
    name = "step_d"
    depends_on = ["step_b", "step_c"]
    produces = ["table_d"]


class CycleStep1(DummyStep):
    name = "cycle_1"
    depends_on = ["cycle_2"]


class CycleStep2(DummyStep):
    name = "cycle_2"
    depends_on = ["cycle_1"]


def test_dag_linear_execution_levels():
    steps = [StepA(), StepB(), StepC(), StepD()]
    dag = DAG(steps)
    levels = dag.get_execution_levels()

    assert len(levels) == 3
    assert [s.name for s in levels[0]] == ["step_a"]
    assert set(s.name for s in levels[1]) == {"step_b", "step_c"}
    assert [s.name for s in levels[2]] == ["step_d"]


def test_dag_cycle_detection():
    steps = [CycleStep1(), CycleStep2()]
    with pytest.raises(ValueError, match="Cycle detected"):
        DAG(steps)


def test_dag_missing_dependency():
    class MissingDepStep(DummyStep):
        name = "missing_dep"
        depends_on = ["non_existent_step"]

    with pytest.raises(ValueError, match="Unknown dependency"):
        DAG([MissingDepStep()])


def test_dag_get_downstream():
    steps = [StepA(), StepB(), StepC(), StepD()]
    dag = DAG(steps)
    downstream = dag.get_downstream("step_a")
    assert downstream == {"step_b", "step_c", "step_d"}

    downstream_b = dag.get_downstream("step_b")
    assert downstream_b == {"step_d"}


def test_dag_topological_sort():
    steps = [StepD(), StepC(), StepB(), StepA()]
    dag = DAG(steps)
    sorted_steps = dag.topological_sort()

    names = [s.name for s in sorted_steps]
    assert names.index("step_a") < names.index("step_b")
    assert names.index("step_a") < names.index("step_c")
    assert names.index("step_b") < names.index("step_d")
    assert names.index("step_c") < names.index("step_d")
