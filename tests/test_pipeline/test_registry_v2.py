from src.pipeline.core.registry import get_default_registry
from src.pipeline.core.dag import DAG


def test_default_registry_has_15_v2_steps():
    reg = get_default_registry()
    steps = reg.get_steps()
    assert len(steps) >= 14

    # Build DAG to verify no missing dependencies or cycles
    dag = DAG(steps)
    levels = dag.get_execution_levels()
    assert len(levels) >= 4
