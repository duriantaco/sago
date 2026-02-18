"""Dependency resolver for task execution ordering."""

import logging
from collections import defaultdict
from typing import Any

from sago.core.parser import Task

logger = logging.getLogger(__name__)


class CircularDependencyError(Exception):
    """Raised when circular dependencies are detected."""

    pass


class DependencyResolver:
    """Resolves task dependencies and creates execution waves."""

    def __init__(self) -> None:
        """Initialize dependency resolver."""
        self.logger = logging.getLogger(self.__class__.__name__)

    def resolve(self, tasks: list[Task]) -> list[list[Task]]:
        """Resolve dependencies and return waves of parallel tasks.

        Args:
            tasks: List of tasks to resolve

        Returns:
            List of waves, where each wave contains tasks that can run in parallel

        Raises:
            CircularDependencyError: If circular dependencies are detected
        """
        if not tasks:
            return []

        # Build dependency graph based on file dependencies
        task_map = {task.id: task for task in tasks}
        graph = self._build_dependency_graph(tasks)

        # Detect circular dependencies
        if self._has_circular_dependency(graph, task_map):
            raise CircularDependencyError("Circular dependencies detected in task graph")

        # Topological sort to create waves
        waves = self._create_execution_waves(graph, task_map)

        # Split waves that have file overlaps to prevent parallel file conflicts
        waves = self._split_overlapping_waves(waves)

        self.logger.info(f"Resolved {len(tasks)} tasks into {len(waves)} waves")
        for i, wave in enumerate(waves, 1):
            self.logger.debug(f"Wave {i}: {[t.id for t in wave]}")

        return waves

    def _build_dependency_graph(self, tasks: list[Task]) -> dict[str, set[str]]:
        """Build dependency graph based on file dependencies.

        A task depends on another if it modifies files that the other task creates.

        Uses a two-pass approach:
        1. First pass: identify which file each task creates (first file in list)
        2. Second pass: build dependencies based on all file references

        Args:
            tasks: List of tasks

        Returns:
            Dictionary mapping task_id -> set of task_ids it depends on
        """
        graph: dict[str, set[str]] = defaultdict(set)
        file_creators: dict[str, str] = {}  # file -> task_id that creates it

        # Sort tasks by ID to process in order
        sorted_tasks = sorted(tasks, key=lambda t: t.id)

        # First pass: identify primary file created by each task
        # We assume the first file in the list is the one being created
        for task in sorted_tasks:
            if task.files:
                primary_file = task.files[0]
                if primary_file not in file_creators:
                    file_creators[primary_file] = task.id

        # Second pass: build dependency graph
        # A task depends on another if it references files created by that task
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

        # Build reverse adjacency list: task_id -> list of tasks that depend on it
        dependents: dict[str, list[str]] = defaultdict(list)
        for task_id, deps in graph.items():
            in_degree[task_id] = len(deps)
            for dep_id in deps:
                dependents[dep_id].append(task_id)

        # Process tasks in waves
        while len(completed) < len(graph):
            # Find all tasks with no remaining dependencies
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

            # Mark completed and update in-degrees via reverse adjacency list
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
        """Get a flat list of tasks in execution order.

        Args:
            tasks: List of tasks to order

        Returns:
            Ordered list of tasks
        """
        waves = self.resolve(tasks)
        return [task for wave in waves for task in wave]

    def visualize_dependencies(self, tasks: list[Task]) -> str:
        """Create a text visualization of task dependencies.

        Args:
            tasks: List of tasks

        Returns:
            String representation of dependency graph
        """
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
