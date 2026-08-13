"""
DAG Builder and Topological Resolver for Pipeline V2.

Builds a Directed Acyclic Graph of steps, validates missing dependencies and cycles,
and computes parallel execution levels and downstream dependencies.
"""

from collections import defaultdict, deque
from typing import Dict, List, Set

from src.pipeline.core.base_step import BaseStep


class DAG:
    """Directed Acyclic Graph manager for pipeline steps."""

    def __init__(self, steps: List[BaseStep]):
        self.steps: Dict[str, BaseStep] = {step.name: step for step in steps}
        self.adj_list: Dict[str, List[str]] = defaultdict(list)  # dep -> dependent
        self.in_degree: Dict[str, int] = defaultdict(int)

        self._validate_and_build()

    def _validate_and_build(self) -> None:
        """Validate missing dependencies and check for cycles."""
        for step in self.steps.values():

            for dep in step.depends_on:
                if dep not in self.steps:
                    raise ValueError(
                        f"Unknown dependency '{dep}' for step '{step.name}'"
                    )
                self.adj_list[dep].append(step.name)

            self.in_degree[step.name] = len(step.depends_on)

        # Cycle detection using DFS
        visited: Dict[str, int] = {name: 0 for name in self.steps}  # 0=WHITE, 1=GRAY, 2=BLACK

        def dfs(node: str, path: List[str]) -> None:
            visited[node] = 1
            for neighbor in self.adj_list[node]:
                if visited[neighbor] == 1:
                    cycle = " -> ".join(path + [neighbor])
                    raise ValueError(f"Cycle detected in pipeline graph involving '{neighbor}': {cycle}")
                elif visited[neighbor] == 0:
                    dfs(neighbor, path + [neighbor])
            visited[node] = 2

        for node in self.steps:
            if visited[node] == 0:
                dfs(node, [node])

    def topological_sort(self) -> List[BaseStep]:
        """Returns steps in topological order."""
        ordered: List[BaseStep] = []
        for level in self.get_execution_levels():
            ordered.extend(level)
        return ordered

    def get_execution_levels(self) -> List[List[BaseStep]]:
        """Groups steps into levels that can be executed in parallel.

        Level 0: steps with no dependencies.
        Level N: steps whose dependencies are all in levels < N.
        """
        levels: List[List[BaseStep]] = []
        in_deg = dict(self.in_degree)
        current_level = [self.steps[name] for name, deg in in_deg.items() if deg == 0]

        while current_level:
            # Sort level deterministic by step name for consistent ordering
            current_level.sort(key=lambda s: s.name)
            levels.append(current_level)

            next_level_candidates: List[BaseStep] = []
            for step in current_level:
                for dependent in self.adj_list[step.name]:
                    in_deg[dependent] -= 1
                    if in_deg[dependent] == 0:
                        next_level_candidates.append(self.steps[dependent])

            current_level = next_level_candidates

        return levels

    def get_downstream(self, step_name: str) -> Set[str]:
        """Returns all steps that depend directly or transitively on step_name."""
        if step_name not in self.steps:
            return set()

        downstream: Set[str] = set()
        queue = deque([step_name])

        while queue:
            curr = queue.popleft()
            for neighbor in self.adj_list[curr]:
                if neighbor not in downstream:
                    downstream.add(neighbor)
                    queue.append(neighbor)

        return downstream
