import logging
from collections import defaultdict

from sago.core.parser import Task

logger = logging.getLogger(__name__)


class CircularDependencyError(Exception):
    pass


class DependencyResolver:
    def __init__(self) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

    def resolve(self, tasks: list[Task]) -> list[list[Task]]:
        if not tasks:
            return []

        task_map = {task.id: task for task in tasks}
        graph = self._build_dependency_graph(tasks)

        if self._has_circular_dependency(graph, task_map):
            raise CircularDependencyError("Circular dependencies detected in task graph")

        waves = self._create_execution_waves(graph, task_map)
        waves = self._split_overlapping_waves(waves)

        self.logger.info(f"Resolved {len(tasks)} tasks into {len(waves)} waves")
        for i, wave in enumerate(waves, 1):
            self.logger.debug(f"Wave {i}: {[t.id for t in wave]}")

        return waves

    def _build_dependency_graph(self, tasks: list[Task]) -> dict[str, set[str]]:
        graph: dict[str, set[str]] = defaultdict(set)
        file_creators: dict[str, str] = {}

        sorted_tasks = sorted(tasks, key=lambda t: t.id)

        # First pass: identify primary file created by each task
        for task in sorted_tasks:
            if task.files:
                primary_file = task.files[0]
                if primary_file not in file_creators:
                    file_creators[primary_file] = task.id

        # Second pass: build dependency graph
        for task in sorted_tasks:
            graph[task.id] = set()

            for file_path in task.files:
                creator_task_id = file_creators.get(file_path)
                if creator_task_id is not None and creator_task_id != task.id:
                    graph[task.id].add(creator_task_id)

        return dict(graph)

    def _has_circular_dependency(
        self, graph: dict[str, set[str]], task_map: dict[str, Task]
    ) -> bool:
        """Check if graph has circular dependencies using DFS.

        Args:
            graph: Dependency graph
            task_map: Map of task_id to Task

        Returns:
            True if circular dependency exists
        """
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def dfs(task_id: str) -> bool:
            visited.add(task_id)
            rec_stack.add(task_id)

            for dep_id in graph.get(task_id, set()):
                if dep_id not in visited:
                    if dfs(dep_id):
                        return True
                elif dep_id in rec_stack:
                    self.logger.error(f"Circular dependency detected: {task_id} -> {dep_id}")
                    return True

            rec_stack.remove(task_id)
            return False

        for task_id in graph:
            if task_id not in visited:
                if dfs(task_id):
                    return True

        return False

    def _create_execution_waves(
        self, graph: dict[str, set[str]], task_map: dict[str, Task]
    ) -> list[list[Task]]:
        """Create execution waves using topological sort.

        Args:
            graph: Dependency graph
            task_map: Map of task_id to Task

        Returns:
            List of waves (each wave is a list of tasks that can run in parallel)
        """
        waves: list[list[Task]] = []
        in_degree: dict[str, int] = {}
        completed: set[str] = set()

        dependents: dict[str, list[str]] = defaultdict(list)
        for task_id, deps in graph.items():
            in_degree[task_id] = len(deps)
            for dep_id in deps:
                dependents[dep_id].append(task_id)

        while len(completed) < len(graph):
            current_wave = [
                task_map[tid]
                for tid, degree in in_degree.items()
                if tid not in completed and degree == 0
            ]

            if not current_wave:
                remaining = set(graph.keys()) - completed
                self.logger.error(f"No tasks ready to execute. Remaining: {remaining}")
                break

            waves.append(current_wave)

            for task in current_wave:
                completed.add(task.id)
                for dependent_id in dependents.get(task.id, []):
                    in_degree[dependent_id] -= 1

        return waves

    def _split_overlapping_waves(self, waves: list[list[Task]]) -> list[list[Task]]:
        """Split waves where tasks write to the same files.

        Only primary files (position 0 in task.files) are considered writes.
        Non-primary files are read-only dependencies and can safely overlap.

        Args:
            waves: Original waves from topological sort

        Returns:
            Waves with write-conflicting tasks separated
        """
        result: list[list[Task]] = []

        for wave in waves:
            safe: list[Task] = []
            claimed_primary_files: set[str] = set()
            overflow: list[Task] = []

            for task in wave:
                primary_file = task.files[0] if task.files else None
                if primary_file and primary_file in claimed_primary_files:
                    self.logger.warning(
                        f"Task {task.id} writes to {primary_file} which another task "
                        f"in this wave also writes, moving to next wave"
                    )
                    overflow.append(task)
                else:
                    safe.append(task)
                    if primary_file:
                        claimed_primary_files.add(primary_file)

            result.append(safe)
            if overflow:
                result.append(overflow)

        return result

    def get_task_order(self, tasks: list[Task]) -> list[Task]:
        waves = self.resolve(tasks)
        return [task for wave in waves for task in wave]

    def visualize_dependencies(self, tasks: list[Task]) -> str:
        graph = self._build_dependency_graph(tasks)
        task_map = {task.id: task for task in tasks}

        lines = ["Task Dependency Graph:", ""]

        for task_id in sorted(graph.keys()):
            task = task_map[task_id]
            deps = graph[task_id]

            if deps:
                dep_str = ", ".join(sorted(deps))
                lines.append(f"  {task_id} ({task.name})")
                lines.append(f"    → depends on: {dep_str}")
            else:
                lines.append(f"  {task_id} ({task.name})")
                lines.append(f"    → no dependencies")

        return "\n".join(lines)
