import time
from pathlib import Path

import pytest

from sago.core.parser import Phase, Task
from sago.web.watcher import (
    ProjectWatcher,
    _is_ignored,
    _load_gitignore_patterns,
)


def _make_phases() -> list[Phase]:
    """Create sample plan phases for testing."""
    return [
        Phase(
            name="Phase 1: Foundation",
            description="Set up project",
            tasks=[
                Task(
                    id="1.1",
                    name="Create config",
                    files=["src/config.py"],
                    action="Create config",
                    verify="pytest",
                    done="Done",
                    phase_name="Phase 1: Foundation",
                ),
                Task(
                    id="1.2",
                    name="Create models",
                    files=["src/models.py"],
                    action="Create models",
                    verify="pytest",
                    done="Done",
                    phase_name="Phase 1: Foundation",
                ),
            ],
        ),
        Phase(
            name="Phase 2: API",
            description="Build API",
            tasks=[
                Task(
                    id="2.1",
                    name="Create routes",
                    files=["src/routes.py"],
                    action="Create routes",
                    verify="pytest",
                    done="Done",
                    phase_name="Phase 2: API",
                ),
            ],
        ),
    ]


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """Create a minimal project directory."""
    (tmp_path / "PROJECT.md").write_text("# Test Project\n")
    (tmp_path / "REQUIREMENTS.md").write_text("# Requirements\n")
    return tmp_path


def test_poll_no_state_file(project_dir: Path) -> None:
    """All tasks should be pending when STATE.md doesn't exist."""
    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    state = watcher.poll()

    assert state.progress.total == 3
    assert state.progress.done == 0
    assert state.progress.failed == 0
    assert state.progress.pct == 0
    assert all(t.status == "pending" for t in state.tasks)


def test_poll_empty_state_file(project_dir: Path) -> None:
    """All tasks should be pending with empty STATE.md."""
    (project_dir / "STATE.md").write_text("")
    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    state = watcher.poll()

    assert state.progress.total == 3
    assert state.progress.done == 0
    assert all(t.status == "pending" for t in state.tasks)


def test_poll_done_tasks(project_dir: Path) -> None:
    """Done tasks should be detected from STATE.md."""
    (project_dir / "STATE.md").write_text(
        "# State\n\n[✓] 1.1: Create config\n[✓] 2.1: Create routes\n"
    )
    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    state = watcher.poll()

    assert state.progress.done == 2
    assert state.progress.total == 3
    assert state.progress.pct == 67

    task_map = {t.id: t for t in state.tasks}
    assert task_map["1.1"].status == "done"
    assert task_map["1.2"].status == "pending"
    assert task_map["2.1"].status == "done"


def test_poll_failed_tasks(project_dir: Path) -> None:
    """Failed tasks should be detected from STATE.md."""
    (project_dir / "STATE.md").write_text("[✓] 1.1: Create config\n[✗] 1.2: Create models\n")
    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    state = watcher.poll()

    assert state.progress.done == 1
    assert state.progress.failed == 1

    task_map = {t.id: t for t in state.tasks}
    assert task_map["1.1"].status == "done"
    assert task_map["1.2"].status == "failed"
    assert task_map["2.1"].status == "pending"


def test_poll_phase_progress(project_dir: Path) -> None:
    """Phase progress should be calculated correctly."""
    (project_dir / "STATE.md").write_text("[✓] 1.1: Create config\n[✓] 1.2: Create models\n")
    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    state = watcher.poll()

    phase_map = {p.name: p for p in state.phases}
    assert phase_map["Phase 1: Foundation"].done == 2
    assert phase_map["Phase 1: Foundation"].total == 2
    assert phase_map["Phase 2: API"].done == 0
    assert phase_map["Phase 2: API"].total == 1


def test_file_change_detection(project_dir: Path) -> None:
    """New files should appear in recent_files."""
    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    # No changes initially
    state = watcher.poll()
    assert len(state.recent_files) == 0

    # Create a tracked file (pyproject.toml is in _COMMON_ROOT_FILES)
    time.sleep(0.05)  # ensure mtime differs
    (project_dir / "pyproject.toml").write_text("[project]\nname = 'test'\n")

    state = watcher.poll()
    paths = [f.path for f in state.recent_files]
    assert "pyproject.toml" in paths

    new_file = next(f for f in state.recent_files if f.path == "pyproject.toml")
    assert new_file.is_new is True
    assert new_file.size > 0


def test_file_modification_detection(project_dir: Path) -> None:
    """Modified files should appear in recent_files as not new."""
    # Create the file first so it's in the baseline
    (project_dir / "README.md").write_text("# Hello\n")

    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    # Modify after baseline
    time.sleep(0.05)
    (project_dir / "README.md").write_text("# Hello World\nUpdated!\n")

    state = watcher.poll()
    paths = [f.path for f in state.recent_files]
    assert "README.md" in paths

    mod_file = next(f for f in state.recent_files if f.path == "README.md")
    assert mod_file.is_new is False


def test_gitignore_patterns(tmp_path: Path) -> None:
    """Gitignore patterns should be loaded and applied."""
    (tmp_path / ".gitignore").write_text("node_modules\n*.pyc\nbuild/\n# comment\n\n")

    patterns = _load_gitignore_patterns(tmp_path)
    assert "node_modules" in patterns
    assert "*.pyc" in patterns
    assert "build" in patterns
    assert "# comment" not in patterns


def test_is_ignored() -> None:
    """Test the ignore pattern matching."""
    patterns = ["node_modules", "*.pyc", "__pycache__", ".git"]

    assert _is_ignored("node_modules", patterns) is True
    assert _is_ignored("src/__pycache__", patterns) is True
    assert _is_ignored("test.pyc", patterns) is True
    assert _is_ignored("src/main.py", patterns) is False
    assert _is_ignored("README.md", patterns) is False


def test_state_caching(project_dir: Path) -> None:
    """Watcher should cache STATE.md parsing until file changes."""
    (project_dir / "STATE.md").write_text("[✓] 1.1: Create config\n")
    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    state1 = watcher.poll()
    state2 = watcher.poll()

    # Same object reference means cache was used
    assert state1.tasks[0].status == state2.tasks[0].status
    assert state1.progress.done == state2.progress.done


def test_poll_state_updates(project_dir: Path) -> None:
    """Watcher should detect STATE.md changes between polls."""
    (project_dir / "STATE.md").write_text("")
    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    state1 = watcher.poll()
    assert state1.progress.done == 0

    # Update STATE.md
    time.sleep(0.05)
    (project_dir / "STATE.md").write_text("[✓] 1.1: Create config\n")

    state2 = watcher.poll()
    assert state2.progress.done == 1


def test_progress_100_percent(project_dir: Path) -> None:
    """100% progress when all tasks are done."""
    (project_dir / "STATE.md").write_text(
        "[✓] 1.1: Create config\n[✓] 1.2: Create models\n[✓] 2.1: Create routes\n"
    )
    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    state = watcher.poll()

    assert state.progress.done == 3
    assert state.progress.total == 3
    assert state.progress.pct == 100


def test_to_dict_serialization(project_dir: Path) -> None:
    """ProjectState.to_dict() should produce JSON-serializable output."""
    import json

    (project_dir / "STATE.md").write_text("[✓] 1.1: Create config\n")
    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    state = watcher.poll()
    d = state.to_dict()

    # Should be JSON-serializable without error
    result = json.dumps(d)
    assert "tasks" in result
    assert "progress" in result
    assert "phases" in result
    assert "recent_files" in result


def test_plan_file_tracking(project_dir: Path) -> None:
    """Files mentioned in plan tasks should be tracked."""
    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    # Create a plan-tracked file
    src_dir = project_dir / "src"
    src_dir.mkdir()
    time.sleep(0.05)
    (src_dir / "config.py").write_text("# config\n")

    state = watcher.poll()
    paths = [f.path for f in state.recent_files]
    assert "src/config.py" in paths


def test_md_files_in_poll(project_dir: Path) -> None:
    """Poll should include md_files with content for existing .md files."""
    (project_dir / "PLAN.md").write_text("# Plan\n\n## Phase 1\n- Task A\n")
    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    state = watcher.poll()

    filenames = [m.filename for m in state.md_files]
    # PROJECT.md and REQUIREMENTS.md were created by the fixture
    assert "PROJECT.md" in filenames
    assert "REQUIREMENTS.md" in filenames
    assert "PLAN.md" in filenames
    # STATE.md doesn't exist so it shouldn't appear
    assert "STATE.md" not in filenames

    plan_md = next(m for m in state.md_files if m.filename == "PLAN.md")
    assert "# Plan" in plan_md.content
    assert plan_md.mtime > 0


def test_md_files_caching(project_dir: Path) -> None:
    """Md file content should be cached and only re-read when mtime changes."""
    (project_dir / "PLAN.md").write_text("# V1\n")
    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    state1 = watcher.poll()
    plan1 = next(m for m in state1.md_files if m.filename == "PLAN.md")
    assert "# V1" in plan1.content

    # Update the file
    time.sleep(0.05)
    (project_dir / "PLAN.md").write_text("# V2\n")

    state2 = watcher.poll()
    plan2 = next(m for m in state2.md_files if m.filename == "PLAN.md")
    assert "# V2" in plan2.content


def test_md_files_serialization(project_dir: Path) -> None:
    """md_files should be included in to_dict() output."""
    import json

    (project_dir / "PLAN.md").write_text("# Plan\n")
    phases = _make_phases()
    watcher = ProjectWatcher(project_path=project_dir, plan_phases=phases)

    state = watcher.poll()
    d = state.to_dict()

    assert "md_files" in d
    result = json.dumps(d)
    assert "md_files" in result
    assert "PLAN.md" in result
