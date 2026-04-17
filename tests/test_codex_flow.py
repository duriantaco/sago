"""End-to-end Codex control-plane flow coverage for the current builder contract."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from sago.cli import app
from sago.models.state import PhaseReview

runner = CliRunner()

TWO_PHASE_PLAN = """# Codex Dogfood Plan

```xml
<phases>
    <phase name="Phase 1: Foundation">
        <description>Build the foundation first.</description>
        <task id="1.1">
            <name>Create config</name>
            <files>config.py</files>
            <action>Create configuration module</action>
            <verify>pytest tests/test_config.py -q</verify>
            <done>Config module exists</done>
        </task>
    </phase>
    <phase name="Phase 2: Delivery">
        <description>Ship the next task only after review.</description>
        <task id="2.1" depends_on="1.1">
            <name>Create main</name>
            <files>main.py</files>
            <action>Create main module</action>
            <verify>pytest tests/test_main.py -q</verify>
            <done>Main module exists</done>
        </task>
    </phase>
</phases>
```
"""


def _write_receipt(
    project_path: Path,
    *,
    task_id: str,
    status: str,
    exit_code: int,
    stdout: str = "",
    stderr: str = "",
    recorded_at: str,
    suffix: str,
) -> Path:
    timestamp = recorded_at.replace("-", "").replace(":", "")
    receipt = {
        "receipt_id": f"receipt-{task_id}-{timestamp}-{suffix}",
        "task_id": task_id,
        "status": status,
        "verify_command": "pytest tests/test_config.py -q",
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": 321,
        "files_changed": [f"{task_id}.py"],
        "recorded_at": recorded_at,
        "builder": "codex",
        "git_head": "abc1234"
    }
    path = project_path / f"{receipt['receipt_id']}.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def test_codex_control_plane_flow_covers_failure_resume_review_and_replan(
    sago_project: Path,
) -> None:
    (sago_project / "PLAN.md").write_text(TWO_PHASE_PLAN, encoding="utf-8")
    (sago_project / "STATE.md").write_text("", encoding="utf-8")

    next_payload = json.loads(
        runner.invoke(app, ["next", "--path", str(sago_project), "--json"]).output
    )
    assert next_payload["state"] == "task"
    assert next_payload["task"]["id"] == "1.1"

    failed_receipt = _write_receipt(
        sago_project,
        task_id="1.1",
        status="failed",
        exit_code=1,
        stderr="AssertionError: config mismatch",
        recorded_at="2026-04-17T09:00:00Z",
        suffix="fail",
    )
    failed = runner.invoke(
        app,
        [
            "checkpoint",
            "1.1",
            "--status",
            "failed",
            "--notes",
            "foundation verify failed",
            "--next",
            "1.1: Retry foundation",
            "--next-action",
            "Fix config mismatch and rerun pytest",
            "--receipt-file",
            str(failed_receipt),
            "--path",
            str(sago_project),
            "--no-git-tag",
            "--json",
        ],
    )
    assert failed.exit_code == 0, failed.output
    failed_payload = json.loads(failed.output)
    assert failed_payload["receipt"]["attached"] is True

    status_after_failure = json.loads(
        runner.invoke(app, ["status", "--path", str(sago_project), "--json"]).output
    )
    assert status_after_failure["state"]["resume_point"]["failure_reason"] == "foundation verify failed"
    assert status_after_failure["evidence_summary"] == {
        "receipts": 1,
        "verified_done": 0,
        "missing_done": 0,
        "repeated_failures": 0,
    }

    success_receipt = _write_receipt(
        sago_project,
        task_id="1.1",
        status="done",
        exit_code=0,
        stdout="1 passed",
        recorded_at="2026-04-17T09:05:00Z",
        suffix="pass",
    )
    done = runner.invoke(
        app,
        [
            "checkpoint",
            "1.1",
            "--status",
            "done",
            "--notes",
            "foundation fixed",
            "--next",
            "2.1: Create main",
            "--next-action",
            "Implement delivery task",
            "--receipt-file",
            str(success_receipt),
            "--path",
            str(sago_project),
            "--no-git-tag",
            "--json",
        ],
    )
    assert done.exit_code == 0, done.output

    status_after_done = json.loads(
        runner.invoke(app, ["status", "--path", str(sago_project), "--json"]).output
    )
    assert status_after_done["state"]["resume_point"]["next_task"] == "2.1: Create main"
    assert status_after_done["evidence_summary"] == {
        "receipts": 2,
        "verified_done": 1,
        "missing_done": 0,
        "repeated_failures": 0,
    }
    assert status_after_done["phase_gates"] == [
        {
            "phase_name": "Phase 1: Foundation",
            "status": "pending_review",
            "reviewed_at": None,
            "blocking_findings": [],
            "summary": ""
        }
    ]

    review = PhaseReview(
        phase_name="Phase 1: Foundation",
        summary="Foundation approved.",
        reviewer="judge",
    )
    mock_review = SimpleNamespace(
        success=True,
        output=review.to_markdown(),
        error=None,
        metadata={"phase_review": review.model_dump(mode="json")},
    )
    async def fake_replan_workflow(*args: object, **kwargs: object) -> SimpleNamespace:
        plan_path = sago_project / "PLAN.md"
        plan_path.write_text(
            plan_path.read_text(encoding="utf-8").replace("Create main", "Create main polished"),
            encoding="utf-8",
        )
        return SimpleNamespace(success=True, error=None)

    with (
        patch("sago.commands.replan_cmd.check_llm_configured"),
        patch(
            "sago.agents.orchestrator.PlanningWorkflow.run_review",
            new_callable=AsyncMock,
            return_value=mock_review,
        ),
        patch(
            "sago.agents.orchestrator.PlanningWorkflow.run_replan_workflow",
            new_callable=AsyncMock,
            side_effect=fake_replan_workflow,
        ),
    ):
        replan = runner.invoke(
            app,
            [
                "replan",
                "--path",
                str(sago_project),
                "--feedback",
                "Continue with the approved foundation and keep the remaining plan stable.",
                "--yes",
            ],
        )

    assert replan.exit_code == 0, replan.output
    assert "Plan updated successfully!" in replan.output
    assert "Create main polished" in (sago_project / "PLAN.md").read_text(encoding="utf-8")

    status_after_review = json.loads(
        runner.invoke(app, ["status", "--path", str(sago_project), "--json"]).output
    )
    assert status_after_review["phase_gates"][0]["status"] == "approved"
    assert status_after_review["memory_summary"]["reviewed_phases"] == ["Phase 1: Foundation"]

    next_after_review = json.loads(
        runner.invoke(app, ["next", "--path", str(sago_project), "--json"]).output
    )
    assert next_after_review["state"] == "task"
    assert next_after_review["task"]["id"] == "2.1"
