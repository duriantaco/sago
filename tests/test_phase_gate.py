"""Phase-gate regression tests for Phase 3."""

import json
from pathlib import Path

from typer.testing import CliRunner

from sago.cli import app
from sago.models.state import PhaseReview, ReviewFinding, ReviewSeverity, TaskStatus
from sago.state import StateManager

runner = CliRunner()

TWO_PHASE_PLAN = """# Test Plan

```xml
<phases>
    <phase name="Phase 1: Foundation">
        <description>Complete the first phase.</description>
        <task id="1.1">
            <name>Create config</name>
            <files>config.py</files>
            <action>Create configuration module</action>
            <verify>python -c "import config"</verify>
            <done>Config module exists</done>
        </task>
    </phase>
    <phase name="Phase 2: Delivery">
        <description>Continue only after review.</description>
        <task id="2.1" depends_on="1.1">
            <name>Create main</name>
            <files>main.py</files>
            <action>Create main module</action>
            <verify>python -c "import main"</verify>
            <done>Main module exists</done>
        </task>
    </phase>
</phases>
```
"""


def _setup_two_phase_project(project_path: Path) -> None:
    (project_path / "PLAN.md").write_text(TWO_PHASE_PLAN, encoding="utf-8")
    StateManager(project_path / "STATE.md").checkpoint(
        task_id="1.1",
        task_name="Create config",
        status=TaskStatus.DONE,
        notes="Config module exists",
        phase_name="Phase 1: Foundation",
        next_task="2.1: Create main",
        next_action="Implement main module",
    )


def test_next_json_blocks_when_completed_phase_needs_review(sago_project: Path) -> None:
    _setup_two_phase_project(sago_project)

    result = runner.invoke(app, ["next", "--path", str(sago_project), "--json"])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert payload["state"] == "blocked"
    assert payload["reason"] == "phase_review_required"
    assert payload["phase"] == "Phase 1: Foundation"
    assert payload["message"] == "Phase review required before continuing."
    assert payload["blocking_findings"] == []


def test_next_json_blocks_when_phase_review_has_critical_findings(sago_project: Path) -> None:
    _setup_two_phase_project(sago_project)
    StateManager(sago_project / "STATE.md").record_phase_review(
        PhaseReview(
            phase_name="Phase 1: Foundation",
            summary="The phase has a blocking issue.",
            findings=[
                ReviewFinding(
                    severity=ReviewSeverity.CRITICAL,
                    message="Config loader ignores missing environment values.",
                    file="config.py",
                    line=12,
                )
            ],
            reviewer="judge",
        )
    )

    result = runner.invoke(app, ["next", "--path", str(sago_project), "--json"])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert payload["state"] == "blocked"
    assert payload["reason"] == "phase_blocked"
    assert payload["phase"] == "Phase 1: Foundation"
    assert payload["message"] == "Phase blocked by review findings."
    assert payload["blocking_findings"] == [
        {
            "severity": "critical",
            "message": "Config loader ignores missing environment values.",
            "file": "config.py",
            "line": 12,
        }
    ]


def test_status_json_surfaces_phase_gates_and_phase_reviews(sago_project: Path) -> None:
    _setup_two_phase_project(sago_project)
    StateManager(sago_project / "STATE.md").record_phase_review(
        PhaseReview(
            phase_name="Phase 1: Foundation",
            summary="Looks good overall.",
            findings=[],
            reviewer="judge",
        )
    )

    result = runner.invoke(app, ["status", "--path", str(sago_project), "--json"])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert payload["phase_gates"] == [
        {
            "phase_name": "Phase 1: Foundation",
            "status": "approved",
            "reviewed_at": payload["phase_gates"][0]["reviewed_at"],
            "blocking_findings": [],
            "summary": "Looks good overall.",
        }
    ]
    assert payload["state"]["phase_reviews"]["Phase 1: Foundation"] == {
        "phase_name": "Phase 1: Foundation",
        "summary": "Looks good overall.",
        "gate_status": "approved",
        "reviewed_at": payload["state"]["phase_reviews"]["Phase 1: Foundation"]["reviewed_at"],
        "reviewer": "judge",
        "finding_count": 0,
        "findings": [],
    }
