"""sago checkpoint command."""

from dataclasses import dataclass, field
from pathlib import Path

import typer

from sago.commands import app, console, load_config, print_json_output
from sago.core.parser import MarkdownParser
from sago.core.project import ProjectManager
from sago.models import Phase
from sago.models.state import TaskStatus
from sago.state import CheckpointResult, StateManager


def _resolve_task_from_plan(
    plan_phases: list[Phase], task_id: str, phase_override: str
) -> tuple[str, str, list[str]]:
    """Find task name, phase name, and phase task IDs from the plan.

    Raises typer.Exit(1) if the task is not found.
    """
    for p in plan_phases:
        for t in p.tasks:
            if t.id == task_id:
                phase_name = phase_override or p.name
                phase_task_ids = [pt.id for pt in p.tasks]
                return t.name, phase_name, phase_task_ids
    raise ValueError(f"Task {task_id} not found in PLAN.md")


@dataclass
class CheckpointParams:
    """Grouped parameters for the checkpoint command."""

    task_id: str
    status: str = "done"
    notes: str = ""
    next_task: str = ""
    next_action: str = ""
    decisions: list[str] = field(default_factory=list)
    phase: str = ""
    git_tag: bool = True


def _print_checkpoint_result(
    params: CheckpointParams,
    task_name: str,
    cp_result: CheckpointResult,
) -> None:
    """Display checkpoint result to the user."""
    icon = {"done": "✓", "failed": "✗", "skipped": "⊘"}[params.status]
    console.print(f"[green][{icon}] {params.task_id}: {task_name}[/green]")
    if params.notes:
        console.print(f"  [dim]{params.notes}[/dim]")
    if params.decisions:
        console.print("  [cyan]Decisions:[/cyan]")
        for d in params.decisions:
            console.print(f"    • {d}")
    if params.next_task:
        console.print(f"  [yellow]Next → {params.next_task}[/yellow]")
    if cp_result.phase_completed:
        console.print(f"\n  [green bold]Phase complete: {cp_result.phase_name}[/green bold]")
        console.print("  [yellow]Run `sago replan` before starting the next phase.[/yellow]")


def _create_checkpoint_git_tag(project_path: Path, task_id: str) -> bool:
    """Create a git tag for a completed checkpoint."""
    import subprocess

    tag_name = f"sago-checkpoint-{task_id}"
    try:
        subprocess.run(
            ["git", "tag", tag_name],
            cwd=project_path,
            capture_output=True,
            check=True,
            timeout=30,
        )
        console.print(f"  [dim]Tagged: {tag_name}[/dim]")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        console.print(f"  [yellow]Tag {tag_name} already exists or git not available[/yellow]")
        return False


def _apply_checkpoint(project_path: Path, params: CheckpointParams) -> dict[str, object]:
    cfg = load_config(project_path)
    manager = ProjectManager(cfg)
    if project_path.exists() and manager.has_any_required_files(project_path):
        missing = manager.missing_required_files(project_path)
        if missing:
            raise ValueError(f"Missing required files: {', '.join(missing)}")
    if not manager.is_sago_project(project_path):
        raise ValueError(f"Not a sago project: {project_path}")

    plan_file = project_path / "PLAN.md"
    if not plan_file.exists():
        raise ValueError("No PLAN.md found.")

    parser = MarkdownParser()
    phases = parser.parse_xml_tasks(plan_file.read_text(encoding="utf-8"))
    task_name, phase_name, phase_task_ids = _resolve_task_from_plan(
        phases,
        params.task_id,
        params.phase,
    )

    task_status = TaskStatus(params.status)
    state_mgr = StateManager(project_path / "STATE.md")
    cp_result = state_mgr.checkpoint(
        task_id=params.task_id,
        task_name=task_name,
        status=task_status,
        notes=params.notes,
        phase_name=phase_name,
        next_task=params.next_task,
        next_action=params.next_action,
        decisions=params.decisions if params.decisions else None,
        phase_task_ids=phase_task_ids,
    )

    git_tag_created = False
    if params.git_tag and task_status == TaskStatus.DONE:
        git_tag_created = _create_checkpoint_git_tag(project_path, params.task_id)

    return {
        "success": True,
        "task_id": params.task_id,
        "task_name": task_name,
        "status": task_status,
        "notes": params.notes,
        "next_task": params.next_task,
        "next_action": params.next_action,
        "decisions": params.decisions,
        "phase_name": phase_name,
        "phase_completed": cp_result.phase_completed,
        "phase_complete_name": cp_result.phase_name,
        "git_tag_created": git_tag_created,
    }


def _do_checkpoint(project_path: Path, params: CheckpointParams) -> None:
    payload = _apply_checkpoint(project_path, params)
    cp_result = CheckpointResult(
        phase_completed=bool(payload["phase_completed"]),
        phase_name=str(payload["phase_complete_name"]),
    )
    _print_checkpoint_result(params, str(payload["task_name"]), cp_result)


@app.command()
def checkpoint(
    task_id: str = typer.Argument(..., help="Task ID (e.g. 1.2)"),
    status: str = typer.Option(
        "done", "--status", "-s", help="Task status: done, failed, or skipped"
    ),
    notes: str = typer.Option("", "--notes", "-n", help="Notes about what happened"),
    next_task: str = typer.Option(
        "", "--next", help="Next task ID and name (e.g. '2.1: Build CLI')"
    ),
    next_action: str = typer.Option("", "--next-action", help="What to do next"),
    decisions: list[str] = typer.Option([], "--decision", "-d", help="Key decision (repeatable)"),
    phase: str = typer.Option("", "--phase", help="Override phase name"),
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
    git_tag: bool = typer.Option(True, "--git-tag/--no-git-tag", help="Create git tag on success"),
    json_output: bool = typer.Option(False, "--json", help="Output structured JSON"),
) -> None:
    """Record a task checkpoint in STATE.md.

    Updates task status, resume point, and optionally records key decisions.
    The coding agent calls this instead of editing STATE.md directly.

    Examples:
        sago checkpoint 1.1 --notes "Config module working"
        sago checkpoint 1.2 -s failed -n "pytest exited 1" --next "1.2: Retry"
        sago checkpoint 2.1 -d "Chose SQLite over Postgres" -d "Using async handlers"
    """
    if status not in ("done", "failed", "skipped"):
        if json_output:
            print_json_output({"success": False, "error": f"Invalid status: {status}"})
            raise typer.Exit(1)
        console.print(f"[red]Invalid status: {status}. Must be done, failed, or skipped.[/red]")
        raise typer.Exit(1)
    try:
        params = CheckpointParams(
            task_id=task_id,
            status=status,
            notes=notes,
            next_task=next_task,
            next_action=next_action,
            decisions=decisions,
            phase=phase,
            git_tag=git_tag,
        )
        if json_output:
            print_json_output(_apply_checkpoint(project_path=project_path, params=params))
            return
        _do_checkpoint(project_path=project_path, params=params)
    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            print_json_output({"success": False, "error": str(e)})
            raise typer.Exit(1) from None
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None
