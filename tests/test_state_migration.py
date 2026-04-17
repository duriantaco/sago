"""Migration and structured-state regression tests for Phase 1."""

import json
from pathlib import Path

from sago.models.plan import Phase, Task
from sago.models.state import PhaseReview, TaskStatus
from sago.state import StateManager
from sago.web.watcher import ProjectWatcher


def _make_phases() -> list[Phase]:
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
        )
    ]


def test_legacy_state_read_materializes_structured_state(tmp_path: Path) -> None:
    state_file = tmp_path / "STATE.md"
    state_file.write_text(
        """# Legacy State

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
""",
        encoding="utf-8",
    )

    mgr = StateManager(state_file)
    task_states = mgr.get_task_states(_make_phases())

    assert {task.task_id: task.status for task in task_states} == {
        "1.1": TaskStatus.DONE,
        "1.2": TaskStatus.PENDING,
    }

    structured_state = tmp_path / ".planning" / "runtime" / "project_state.json"
    assert structured_state.exists()
    payload = json.loads(structured_state.read_text(encoding="utf-8"))
    assert payload["active_phase"] == "Phase 1: Foundation"
    assert payload["current_task"] == "1.2: Create main"
    assert payload["resume_point"]["checkpoint"] == "sago-checkpoint-1.1"
    assert payload["task_records"] == [
        {
            "task_id": "1.1",
            "task_name": "Create config",
            "status": "done",
            "note": "Config module exists",
        }
    ]


def test_checkpoint_writes_structured_state_and_rendered_markdown(tmp_path: Path) -> None:
    state_file = tmp_path / "STATE.md"
    mgr = StateManager(state_file)

    mgr.checkpoint(
        task_id="1.1",
        task_name="Create config",
        status=TaskStatus.DONE,
        notes="Config module working",
        phase_name="Phase 1: Foundation",
        next_task="1.2: Create main",
        next_action="Implement main module",
        decisions=["Using pydantic"],
    )

    structured_state = tmp_path / ".planning" / "runtime" / "project_state.json"
    assert structured_state.exists()
    payload = json.loads(structured_state.read_text(encoding="utf-8"))
    assert payload["task_records"] == [
        {
            "task_id": "1.1",
            "task_name": "Create config",
            "status": "done",
            "note": "Config module working",
        }
    ]
    assert payload["decisions"] == ["Using pydantic"]

    rendered = state_file.read_text(encoding="utf-8")
    assert "* **Active Phase:** Phase 1: Foundation" in rendered
    assert "* **Current Task:** 1.2: Create main" in rendered
    assert "[✓] 1.1: Create config — Config module working" in rendered
    assert "## Key Decisions" in rendered


def test_structured_state_drives_reads_when_state_md_is_missing(tmp_path: Path) -> None:
    state_file = tmp_path / "STATE.md"
    mgr = StateManager(state_file)
    mgr.checkpoint(
        task_id="1.1",
        task_name="Create config",
        status=TaskStatus.DONE,
        notes="Done",
        phase_name="Phase 1: Foundation",
        next_task="1.2: Create main",
        next_action="Implement main module",
    )

    state_file.unlink()

    fresh_mgr = StateManager(state_file)
    task_states = fresh_mgr.get_task_states(_make_phases())

    assert {task.task_id: task.status for task in task_states} == {
        "1.1": TaskStatus.DONE,
        "1.2": TaskStatus.PENDING,
    }
    assert fresh_mgr.get_resume_point() is not None
    assert state_file.exists()


def test_phase_metadata_round_trips_through_structured_state(tmp_path: Path) -> None:
    state_file = tmp_path / "STATE.md"
    mgr = StateManager(state_file)

    mgr.mark_phase_complete("Phase 1: Foundation")
    mgr.append_phase_summary("Phase 1: Foundation", "Everything looks good.")

    structured_state = tmp_path / ".planning" / "runtime" / "project_state.json"
    payload = json.loads(structured_state.read_text(encoding="utf-8"))
    assert payload["phase_completions"] == ["Phase 1: Foundation"]
    assert payload["phase_summaries"] == {"Phase 1: Foundation": "Everything looks good."}

    fresh_mgr = StateManager(state_file)
    assert fresh_mgr.has_phase_summary("Phase 1: Foundation") is True

    rendered = state_file.read_text(encoding="utf-8")
    assert "## Phase Complete: Phase 1: Foundation" in rendered
    assert "## Phase Review: Phase 1: Foundation" in rendered
    assert "* **Gate:** approved" in rendered
    assert "Everything looks good." in rendered


def test_structured_phase_review_raw_output_survives_reload(tmp_path: Path) -> None:
    state_file = tmp_path / "STATE.md"
    mgr = StateManager(state_file)
    mgr.record_phase_review(
        PhaseReview(
            phase_name="Phase 1: Foundation",
            summary="Approved.",
            reviewer="judge",
            raw_output='{"summary":"Approved.","findings":[]}',
        )
    )

    fresh_mgr = StateManager(state_file)
    review = fresh_mgr.get_phase_review("Phase 1: Foundation")

    assert review is not None
    assert review.raw_output == '{"summary":"Approved.","findings":[]}'


def test_removed_task_records_remain_visible_for_scope_drift_detection(tmp_path: Path) -> None:
    state_file = tmp_path / "STATE.md"
    mgr = StateManager(state_file)
    mgr.checkpoint(
        task_id="9.9",
        task_name="Legacy task",
        status=TaskStatus.DONE,
        notes="Old plan task",
    )

    task_states = mgr.get_task_states(_make_phases())
    task_ids = {task.task_id for task in task_states}

    assert "9.9" in task_ids


def test_watcher_uses_structured_state_without_state_md(tmp_path: Path) -> None:
    (tmp_path / "PROJECT.md").write_text("# Project\n", encoding="utf-8")
    (tmp_path / "REQUIREMENTS.md").write_text("# Requirements\n", encoding="utf-8")

    state_file = tmp_path / "STATE.md"
    mgr = StateManager(state_file)
    mgr.checkpoint(
        task_id="1.1",
        task_name="Create config",
        status=TaskStatus.DONE,
        notes="Done",
        phase_name="Phase 1: Foundation",
        next_task="1.2: Create main",
        next_action="Implement main module",
    )
    state_file.unlink()

    watcher = ProjectWatcher(project_path=tmp_path, plan_phases=_make_phases())
    state = watcher.poll()

    task_map = {task.id: task.status for task in state.tasks}
    assert task_map["1.1"] == "done"
    assert task_map["1.2"] == "pending"
    assert state.progress.done == 1
