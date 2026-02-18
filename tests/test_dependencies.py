"""Tests for dependency resolver."""

import pytest

from sago.agents.dependencies import CircularDependencyError, DependencyResolver
from sago.core.parser import Task


@pytest.fixture
def sample_tasks() -> list[Task]:
    """Create sample tasks with dependencies."""
    return [
        Task(
            id="1.1",
            name="Create config",
            phase_name="Phase 1",
            files=["config.py"],
            action="Create config module",
            verify="python -c 'import config'",
            done="Config module exists",
        ),
        Task(
            id="1.2",
            name="Create database",
            phase_name="Phase 1",
            files=["database.py", "config.py"],  # Depends on config.py from 1.1
            action="Create database module",
            verify="python -c 'import database'",
            done="Database module exists",
        ),
        Task(
            id="1.3",
            name="Create models",
            phase_name="Phase 1",
            files=["models.py", "database.py"],  # Depends on database.py from 1.2
            action="Create models",
            verify="python -c 'import models'",
            done="Models exist",
        ),
        Task(
            id="2.1",
            name="Create API",
            phase_name="Phase 2",
            files=["api.py", "models.py"],  # Depends on models.py from 1.3
            action="Create API",
            verify="python -c 'import api'",
            done="API exists",
        ),
        Task(
            id="2.2",
            name="Create tests",
            phase_name="Phase 2",
            files=["tests.py"],  # Independent
            action="Create tests",
            verify="pytest tests.py",
            done="Tests pass",
        ),
    ]


@pytest.fixture
def circular_tasks() -> list[Task]:
    """Create tasks with circular dependencies.

    Circular dependency chain:
    - Task 1.1: creates a.py, needs c.py (from 3.1)
    - Task 2.1: creates b.py, needs a.py (from 1.1)
    - Task 3.1: creates c.py, needs b.py (from 2.1)

    This creates: 1.1 -> 3.1 -> 2.1 -> 1.1 (circular!)
    """
    return [
        Task(
            id="1.1",
            name="Task A",
            phase_name="Phase 1",
            files=["a.py", "c.py"],  # Creates a.py, needs c.py (from 3.1)
            action="Create A",
            verify="python -c 'import a'",
            done="A exists",
        ),
        Task(
            id="2.1",
            name="Task B",
            phase_name="Phase 2",
            files=["b.py", "a.py"],  # Creates b.py, needs a.py (from 1.1)
            action="Create B",
            verify="python -c 'import b'",
            done="B exists",
        ),
        Task(
            id="3.1",
            name="Task C",
            phase_name="Phase 3",
            files=["c.py", "b.py"],  # Creates c.py, needs b.py (from 2.1)
            action="Create C",
            verify="python -c 'import c'",
            done="C exists",
        ),
    ]


def test_resolver_initialization():
    """Test DependencyResolver initialization."""
    resolver = DependencyResolver()
    assert resolver is not None
    assert resolver.logger is not None


def test_resolve_empty_tasks():
    """Test resolving empty task list."""
    resolver = DependencyResolver()
    waves = resolver.resolve([])
    assert waves == []


def test_resolve_single_task():
    """Test resolving single task."""
    resolver = DependencyResolver()
    task = Task(
        id="1.1",
        name="Single task",
        phase_name="Phase 1",
        files=["main.py"],
        action="Create main",
        verify="python main.py",
        done="Main exists",
    )

    waves = resolver.resolve([task])

    assert len(waves) == 1
    assert len(waves[0]) == 1
    assert waves[0][0] == task


def test_resolve_linear_dependencies(sample_tasks):
    """Test resolving tasks with linear dependencies."""
    resolver = DependencyResolver()

    # Use subset with linear deps: 1.1 -> 1.2 -> 1.3
    tasks = [sample_tasks[0], sample_tasks[1], sample_tasks[2]]
    waves = resolver.resolve(tasks)

    # Should create 3 waves (one per task in sequence)
    assert len(waves) == 3
    assert waves[0][0].id == "1.1"  # config first
    assert waves[1][0].id == "1.2"  # database second
    assert waves[2][0].id == "1.3"  # models third


def test_resolve_parallel_tasks(sample_tasks):
    """Test resolving tasks that can run in parallel."""
    resolver = DependencyResolver()
    waves = resolver.resolve(sample_tasks)

    # Last two tasks (2.1 and 2.2) can run in parallel
    # 2.1 depends on 1.3, 2.2 is independent
    assert len(waves) >= 3

    # First wave should be task 1.1 (no dependencies)
    assert len(waves[0]) >= 1
    assert any(t.id == "1.1" for t in waves[0])


def test_build_dependency_graph(sample_tasks):
    """Test building dependency graph."""
    resolver = DependencyResolver()
    graph = resolver._build_dependency_graph(sample_tasks)

    # Check dependencies are correct
    assert "1.1" in graph
    assert len(graph["1.1"]) == 0  # No dependencies

    assert "1.2" in graph
    assert "1.1" in graph["1.2"]  # Depends on 1.1

    assert "1.3" in graph
    assert "1.2" in graph["1.3"]  # Depends on 1.2


def test_detect_circular_dependency(circular_tasks):
    """Test detecting circular dependencies."""
    resolver = DependencyResolver()

    with pytest.raises(CircularDependencyError):
        resolver.resolve(circular_tasks)


def test_no_circular_dependency_for_valid_tasks(sample_tasks):
    """Test that valid tasks don't trigger circular dependency error."""
    resolver = DependencyResolver()
    graph = resolver._build_dependency_graph(sample_tasks)
    task_map = {task.id: task for task in sample_tasks}

    has_circular = resolver._has_circular_dependency(graph, task_map)
    assert not has_circular


def test_get_task_order(sample_tasks):
    """Test getting flat task order."""
    resolver = DependencyResolver()
    ordered = resolver.get_task_order(sample_tasks)

    assert len(ordered) == len(sample_tasks)

    # Verify ordering respects dependencies
    task_positions = {task.id: i for i, task in enumerate(ordered)}

    # 1.1 must come before 1.2
    assert task_positions["1.1"] < task_positions["1.2"]

    # 1.2 must come before 1.3
    assert task_positions["1.2"] < task_positions["1.3"]

    # 1.3 must come before 2.1
    assert task_positions["1.3"] < task_positions["2.1"]


def test_visualize_dependencies(sample_tasks):
    """Test dependency visualization."""
    resolver = DependencyResolver()
    viz = resolver.visualize_dependencies(sample_tasks)

    assert "Task Dependency Graph" in viz
    assert "1.1" in viz
    assert "no dependencies" in viz  # 1.1 has no deps
    assert "depends on" in viz  # Other tasks have deps


def test_independent_tasks():
    """Test tasks with no file dependencies run in parallel."""
    resolver = DependencyResolver()

    tasks = [
        Task(
            id="1.1",
            name="Task A",
            phase_name="Phase 1",
            files=["a.py"],
            action="Create A",
            verify="python -c 'import a'",
            done="A exists",
        ),
        Task(
            id="1.2",
            name="Task B",
            phase_name="Phase 1",
            files=["b.py"],
            action="Create B",
            verify="python -c 'import b'",
            done="B exists",
        ),
        Task(
            id="1.3",
            name="Task C",
            phase_name="Phase 1",
            files=["c.py"],
            action="Create C",
            verify="python -c 'import c'",
            done="C exists",
        ),
    ]

    waves = resolver.resolve(tasks)

    # All tasks should be in first wave since they're independent
    assert len(waves) == 1
    assert len(waves[0]) == 3


def test_task_modifying_same_file():
    """Test tasks that modify the same file are ordered."""
    resolver = DependencyResolver()

    tasks = [
        Task(
            id="1.1",
            name="Create file",
            phase_name="Phase 1",
            files=["shared.py"],
            action="Create shared.py",
            verify="python -c 'import shared'",
            done="File exists",
        ),
        Task(
            id="1.2",
            name="Update file",
            phase_name="Phase 1",
            files=["shared.py"],  # Modifies same file
            action="Update shared.py",
            verify="python -c 'import shared'",
            done="File updated",
        ),
    ]

    waves = resolver.resolve(tasks)

    # Tasks should be in separate waves
    assert len(waves) == 2
    assert waves[0][0].id == "1.1"
    assert waves[1][0].id == "1.2"


def test_complex_dependency_graph():
    """Test resolving complex dependency graph."""
    resolver = DependencyResolver()

    tasks = [
        Task(id="1", name="A", phase_name="P1", files=["a.py"], action="", verify="", done=""),
        Task(id="2", name="B", phase_name="P1", files=["b.py", "a.py"], action="", verify="", done=""),
        Task(id="3", name="C", phase_name="P1", files=["c.py", "a.py"], action="", verify="", done=""),
        Task(id="4", name="D", phase_name="P1", files=["d.py", "b.py", "c.py"], action="", verify="", done=""),
    ]

    waves = resolver.resolve(tasks)

    # Wave 1: task 1 (no deps)
    # Wave 2: tasks 2 and 3 (both depend only on 1)
    # Wave 3: task 4 (depends on 2 and 3)
    assert len(waves) == 3
    assert len(waves[0]) == 1  # Task 1
    assert len(waves[1]) == 2  # Tasks 2 and 3
    assert len(waves[2]) == 1  # Task 4
