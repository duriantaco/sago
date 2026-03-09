"""Tests for StateManager — the single authority for STATE.md reads and writes."""

from pathlib import Path

from sago.models.plan import Phase, Task
from sago.models.state import TaskStatus
from sago.state import StateManager


INITIAL_STATE = """\
# Test State

## Current Context

* **Active Phase:** Not started
* **Current Task:** None

## Resume Point

* **Last Completed:** None
* **Next Task:** None
* **Next Action:** None
* **Failure Reason:** None
* **Checkpoint:** None

## Completed Tasks
"""


def _make_manager(tmp_path: Path, content: str = INITIAL_STATE) -> StateManager:
    state_file = tmp_path / "STATE.md"
    state_file.write_text(content, encoding="utf-8")
    return StateManager(state_file)


def _make_phases() -> list[Phase]:
    """Helper to create test phases."""
    return [
        Phase(
            name="Phase 1: Foundation",
            description="Setup",
            tasks=[
                Task(
                    id="1.1",
                    name="Create config",
                    files=["config.py"],
                    action="Create config",
                    verify="python -c 'import config'",
                    done="Config exists",
                    phase_name="Phase 1: Foundation",
                ),
                Task(
                    id="1.2",
                    name="Create main",
                    files=["main.py"],
                    action="Create main",
                    verify="python -c 'import main'",
                    done="Main exists",
                    phase_name="Phase 1: Foundation",
                ),
            ],
        ),
        Phase(
            name="Phase 2: Features",
            description="Build features",
            tasks=[
                Task(
                    id="2.1",
                    name="Build CLI",
                    files=["cli.py"],
                    action="Create CLI",
                    verify="cli --help",
                    done="CLI works",
                    phase_name="Phase 2: Features",
                ),
            ],
        ),
    ]


# ------------------------------------------------------------------
# Write tests
# ------------------------------------------------------------------


def test_checkpoint_done(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.checkpoint(
        task_id="1.1",
        task_name="Create config",
        status=TaskStatus.DONE,
        notes="Config module working",
        phase_name="Phase 1: Foundation",
        next_task="1.2: Create main",
        next_action="Create main module",
    )

    content = mgr.path.read_text(encoding="utf-8")
    assert "[✓] 1.1: Create config — Config module working" in content
    assert "* **Last Completed:** 1.1: Create config" in content
    assert "* **Next Task:** 1.2: Create main" in content
    assert "* **Next Action:** Create main module" in content
    assert "* **Failure Reason:** None" in content
    assert "* **Checkpoint:** sago-checkpoint-1.1" in content
    assert "* **Active Phase:** Phase 1: Foundation" in content


def test_checkpoint_failed(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.checkpoint(
        task_id="1.2",
        task_name="Create main",
        status=TaskStatus.FAILED,
        notes="pytest exited 1",
        next_task="1.2: Create main (retry)",
        next_action="Fix import error",
    )

    content = mgr.path.read_text(encoding="utf-8")
    assert "[✗] 1.2: Create main — pytest exited 1" in content
    assert "* **Failure Reason:** pytest exited 1" in content
    assert "* **Checkpoint:** None" in content


def test_checkpoint_skipped(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.checkpoint(
        task_id="1.3",
        task_name="Optional task",
        status=TaskStatus.SKIPPED,
        notes="Not needed",
    )

    content = mgr.path.read_text(encoding="utf-8")
    assert "[⊘] 1.3: Optional task — Not needed" in content


def test_checkpoint_with_decisions(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.checkpoint(
        task_id="2.1",
        task_name="Auth system",
        status=TaskStatus.DONE,
        notes="Done",
        decisions=["Chose JWT over sessions", "Using bcrypt"],
    )

    content = mgr.path.read_text(encoding="utf-8")
    assert "## Key Decisions" in content
    assert "* Chose JWT over sessions" in content
    assert "* Using bcrypt" in content


def test_checkpoint_idempotent(tmp_path: Path) -> None:
    """Re-checkpointing the same task should replace, not duplicate."""
    mgr = _make_manager(tmp_path)
    mgr.checkpoint(
        task_id="1.1",
        task_name="Create config",
        status=TaskStatus.DONE,
        notes="First attempt",
    )
    mgr.checkpoint(
        task_id="1.1",
        task_name="Create config",
        status=TaskStatus.DONE,
        notes="Second attempt",
    )

    content = mgr.path.read_text(encoding="utf-8")
    assert content.count("[✓] 1.1:") == 1
    assert "Second attempt" in content
    assert "First attempt" not in content


def test_multiple_checkpoints(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.checkpoint(
        task_id="1.1",
        task_name="Task A",
        status=TaskStatus.DONE,
        notes="Done",
        next_task="1.2: Task B",
    )
    mgr.checkpoint(
        task_id="1.2",
        task_name="Task B",
        status=TaskStatus.DONE,
        notes="Also done",
        next_task="2.1: Task C",
    )

    content = mgr.path.read_text(encoding="utf-8")
    assert "[✓] 1.1: Task A — Done" in content
    assert "[✓] 1.2: Task B — Also done" in content
    # Resume point should reflect the latest
    assert "* **Last Completed:** 1.2: Task B" in content
    assert "* **Next Task:** 2.1: Task C" in content


def test_mark_phase_complete(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.mark_phase_complete("Phase 1: Foundation")

    content = mgr.path.read_text(encoding="utf-8")
    assert "## Phase Complete: Phase 1: Foundation" in content


def test_mark_phase_complete_idempotent(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.mark_phase_complete("Phase 1: Foundation")
    mgr.mark_phase_complete("Phase 1: Foundation")

    content = mgr.path.read_text(encoding="utf-8")
    assert content.count("## Phase Complete: Phase 1: Foundation") == 1


def test_checkpoint_no_state_file(tmp_path: Path) -> None:
    """StateManager should create STATE.md if it doesn't exist."""
    state_file = tmp_path / "STATE.md"
    mgr = StateManager(state_file)
    mgr.checkpoint(
        task_id="1.1",
        task_name="First task",
        status=TaskStatus.DONE,
        notes="Created from scratch",
    )

    assert state_file.exists()
    content = state_file.read_text(encoding="utf-8")
    assert "[✓] 1.1: First task — Created from scratch" in content


def test_append_phase_summary(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.append_phase_summary("Phase 1: Foundation", "All tasks look good.")

    content = mgr.path.read_text(encoding="utf-8")
    assert "## Phase Summary: Phase 1: Foundation" in content
    assert "All tasks look good." in content


def test_append_phase_summary_idempotent(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.append_phase_summary("Phase 1: Foundation", "Review A")
    mgr.append_phase_summary("Phase 1: Foundation", "Review B")

    content = mgr.path.read_text(encoding="utf-8")
    assert content.count("## Phase Summary: Phase 1: Foundation") == 1


# ------------------------------------------------------------------
# Read tests — task_status
# ------------------------------------------------------------------


def test_task_status_read(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)

    assert mgr.task_status("1.1") == TaskStatus.PENDING

    mgr.checkpoint(task_id="1.1", task_name="A", status=TaskStatus.DONE)
    assert mgr.task_status("1.1") == TaskStatus.DONE

    mgr.checkpoint(task_id="1.2", task_name="B", status=TaskStatus.FAILED)
    assert mgr.task_status("1.2") == TaskStatus.FAILED


# ------------------------------------------------------------------
# Read tests — get_task_states (replaces parse_state_tasks)
# ------------------------------------------------------------------


def test_get_task_states_all_pending(tmp_path: Path) -> None:
    content = "# STATE.md\n\n## Current Context\n"
    mgr = _make_manager(tmp_path, content)
    phases = _make_phases()

    results = mgr.get_task_states(phases)

    assert len(results) == 3
    assert all(r.status == TaskStatus.PENDING for r in results)
    assert results[0].task_id == "1.1"


def test_get_task_states_done_and_failed(tmp_path: Path) -> None:
    content = """\
## Completed Tasks
[✓] 1.1: Create config — Config exists
[✗] 1.2: Create main — ImportError
"""
    mgr = _make_manager(tmp_path, content)
    phases = _make_phases()

    results = mgr.get_task_states(phases)

    by_id = {r.task_id: r for r in results}
    assert by_id["1.1"].status == TaskStatus.DONE
    assert by_id["1.2"].status == TaskStatus.FAILED
    assert by_id["2.1"].status == TaskStatus.PENDING


def test_get_task_states_all_done(tmp_path: Path) -> None:
    content = """\
[✓] 1.1: Create config
[✓] 1.2: Create main
[✓] 2.1: Build CLI
"""
    mgr = _make_manager(tmp_path, content)
    phases = _make_phases()

    results = mgr.get_task_states(phases)

    assert all(r.status == TaskStatus.DONE for r in results)


def test_get_task_states_with_skipped(tmp_path: Path) -> None:
    content = """\
[✓] 1.1: Create config
[⊘] 1.2: Create main — skipped
"""
    mgr = _make_manager(tmp_path, content)
    phases = _make_phases()

    results = mgr.get_task_states(phases)
    by_id = {r.task_id: r for r in results}
    assert by_id["1.1"].status == TaskStatus.DONE
    assert by_id["1.2"].status == TaskStatus.SKIPPED


# ------------------------------------------------------------------
# Read tests — completed_task_ids
# ------------------------------------------------------------------


def test_completed_task_ids(tmp_path: Path) -> None:
    content = """\
[✓] 1.1: Create config
[✗] 1.2: Create main
[✓] 2.1: Build CLI
"""
    mgr = _make_manager(tmp_path, content)
    assert mgr.completed_task_ids() == ["1.1", "2.1"]


def test_completed_task_ids_empty(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    assert mgr.completed_task_ids() == []


# ------------------------------------------------------------------
# Read tests — get_resume_point
# ------------------------------------------------------------------


def test_get_resume_point(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    mgr.checkpoint(
        task_id="1.1",
        task_name="Create config",
        status=TaskStatus.DONE,
        next_task="1.2: Create main",
        next_action="Build it",
    )

    rp = mgr.get_resume_point()
    assert rp is not None
    assert rp.last_completed == "1.1: Create config"
    assert rp.next_task == "1.2: Create main"
    assert rp.next_action == "Build it"
    assert rp.checkpoint == "sago-checkpoint-1.1"


def test_get_resume_point_none(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    assert mgr.get_resume_point() is None


def test_get_resume_point_after_failure(tmp_path: Path) -> None:
    content = """\
## Resume Point

* **Last Completed:** 1.1: Initialize Project
* **Next Task:** 1.2: Add Configuration (retry)
* **Next Action:** Fix config loading for nested keys
* **Failure Reason:** pytest tests/test_config.py exited 1 — KeyError on nested.key
* **Checkpoint:** sago-checkpoint-1.1

## Completed Tasks
"""
    mgr = _make_manager(tmp_path, content)

    rp = mgr.get_resume_point()
    assert rp is not None
    assert rp.next_task == "1.2: Add Configuration (retry)"
    assert "KeyError" in rp.failure_reason
    assert rp.checkpoint == "sago-checkpoint-1.1"


def test_get_resume_point_all_none_returns_none(tmp_path: Path) -> None:
    content = """\
## Resume Point

* **Last Completed:** None
* **Next Task:** None
* **Next Action:** None
* **Failure Reason:** None
* **Checkpoint:** None

## Completed Tasks
"""
    mgr = _make_manager(tmp_path, content)
    assert mgr.get_resume_point() is None


def test_get_resume_point_missing_section(tmp_path: Path) -> None:
    content = """\
## Current Context

* **Active Phase:** Phase 1

## Completed Tasks
"""
    mgr = _make_manager(tmp_path, content)
    assert mgr.get_resume_point() is None


# ------------------------------------------------------------------
# Read tests — get_project_state
# ------------------------------------------------------------------


def test_get_project_state(tmp_path: Path) -> None:
    content = """\
# Test State

## Current Context

* **Active Phase:** Phase 1: Foundation
* **Current Task:** 1.2: Create main

## Resume Point

* **Last Completed:** 1.1: Create config
* **Next Task:** 1.2: Create main
* **Next Action:** Create main module
* **Failure Reason:** None
* **Checkpoint:** sago-checkpoint-1.1

## Completed Tasks
[✓] 1.1: Create config — Config module exists

## Key Decisions
* Chose YAML over JSON
"""
    mgr = _make_manager(tmp_path, content)
    phases = _make_phases()

    state = mgr.get_project_state(phases)

    assert state.active_phase == "Phase 1: Foundation"
    assert state.current_task == "1.2: Create main"
    assert state.resume_point is not None
    assert state.resume_point.last_completed == "1.1: Create config"
    assert len(state.task_states) == 3
    assert state.completed_task_ids() == {"1.1"}
    assert state.pending_task_ids() == {"1.2", "2.1"}
    assert "Chose YAML over JSON" in state.decisions


def test_get_project_state_empty(tmp_path: Path) -> None:
    """Empty state file produces valid ProjectState with all pending."""
    mgr = _make_manager(tmp_path)
    phases = _make_phases()

    state = mgr.get_project_state(phases)
    assert all(ts.status == TaskStatus.PENDING for ts in state.task_states)
    assert state.resume_point is None


# ------------------------------------------------------------------
# Validation
# ------------------------------------------------------------------


def test_validate_valid_state(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    result = mgr.validate()
    assert result.valid
    assert result.warnings == []


def test_validate_missing_sections(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path, "# Just a title\n")
    result = mgr.validate()
    assert not result.valid
    assert len(result.warnings) == 3  # Missing all three sections


def test_validate_duplicate_tasks(tmp_path: Path) -> None:
    content = """\
## Current Context
## Resume Point
## Completed Tasks
[✓] 1.1: Task A
[✓] 1.1: Task A again
"""
    mgr = _make_manager(tmp_path, content)
    result = mgr.validate()
    assert not result.valid
    assert any("Duplicate" in w for w in result.warnings)


def test_validate_empty_file(tmp_path: Path) -> None:
    """Empty/missing file is valid (project not started)."""
    state_file = tmp_path / "STATE.md"
    mgr = StateManager(state_file)
    result = mgr.validate()
    assert result.valid


# ------------------------------------------------------------------
# Auto phase detection
# ------------------------------------------------------------------


def test_checkpoint_auto_phase_complete(tmp_path: Path) -> None:
    """Completing the last task in a phase auto-marks it complete."""
    mgr = _make_manager(tmp_path)

    # Complete first task
    mgr.checkpoint(
        task_id="1.1",
        task_name="Create config",
        status=TaskStatus.DONE,
        phase_name="Phase 1: Foundation",
        phase_task_ids=["1.1", "1.2"],
    )
    content = mgr.path.read_text(encoding="utf-8")
    assert "## Phase Complete:" not in content

    # Complete second task — should trigger phase complete
    result = mgr.checkpoint(
        task_id="1.2",
        task_name="Create main",
        status=TaskStatus.DONE,
        phase_name="Phase 1: Foundation",
        phase_task_ids=["1.1", "1.2"],
    )
    assert result.phase_completed
    assert result.phase_name == "Phase 1: Foundation"
    content = mgr.path.read_text(encoding="utf-8")
    assert "## Phase Complete: Phase 1: Foundation" in content


def test_checkpoint_no_auto_phase_when_incomplete(tmp_path: Path) -> None:
    """Phase is not marked complete when tasks remain."""
    mgr = _make_manager(tmp_path)
    result = mgr.checkpoint(
        task_id="1.1",
        task_name="Create config",
        status=TaskStatus.DONE,
        phase_name="Phase 1: Foundation",
        phase_task_ids=["1.1", "1.2"],
    )
    assert not result.phase_completed


def test_checkpoint_no_auto_phase_on_failure(tmp_path: Path) -> None:
    """Failed tasks don't trigger phase completion."""
    mgr = _make_manager(tmp_path)
    mgr.checkpoint(
        task_id="1.1",
        task_name="A",
        status=TaskStatus.DONE,
        phase_task_ids=["1.1", "1.2"],
        phase_name="P1",
    )
    result = mgr.checkpoint(
        task_id="1.2",
        task_name="B",
        status=TaskStatus.FAILED,
        phase_task_ids=["1.1", "1.2"],
        phase_name="P1",
    )
    assert not result.phase_completed


def test_checkpoint_returns_result_without_phase_ids(tmp_path: Path) -> None:
    """Without phase_task_ids, no auto-detection but still returns result."""
    mgr = _make_manager(tmp_path)
    result = mgr.checkpoint(
        task_id="1.1",
        task_name="Create config",
        status=TaskStatus.DONE,
    )
    assert not result.phase_completed
