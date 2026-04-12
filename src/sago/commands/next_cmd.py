"""sago next command."""

from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel
from rich.table import Table

from sago.commands import app, console, load_config, print_json_output
from sago.core.parser import MarkdownParser
from sago.core.project import ProjectManager
from sago.models import Phase, Task
from sago.models.state import TaskState, TaskStatus
from sago.state import StateManager
from sago.utils.agent_context import load_agent_context


def _check_deps_met(task: Task, phase: Phase, status_by_id: dict[str, TaskStatus]) -> bool:
    """Return True if all dependencies (explicit or implicit) are satisfied."""
    if task.depends_on:
        return all(status_by_id.get(dep) == TaskStatus.DONE for dep in task.depends_on)
    prior_ids = [t.id for t in phase.tasks[: phase.tasks.index(task)]]
    return all(status_by_id.get(pid) == TaskStatus.DONE for pid in prior_ids)


def _print_next_task(
    task: Task,
    phase: Phase,
    status_by_id: dict[str, TaskStatus],
    state_mgr: StateManager,
    agent_context: dict[str, Any],
) -> None:
    """Display full details of the next actionable task."""
    from sago.validation import check_verify_safety

    console.print(Panel(f"[bold]{task.id}: {task.name}[/bold]", title="Next Task"))

    info_table = Table(show_header=False, padding=(0, 2))
    info_table.add_row("[cyan]Phase[/cyan]", phase.name)
    info_table.add_row("[cyan]Files[/cyan]", "\n".join(task.files) if task.files else "—")
    info_table.add_row("[cyan]Verify[/cyan]", task.verify or "—")
    info_table.add_row("[cyan]Done[/cyan]", task.done or "—")
    console.print(info_table)

    if task.verify:
        for warning in check_verify_safety(task.verify):
            console.print(f"  [red]⚠ SAFETY:[/red] [yellow]{warning}[/yellow]")

    if task.depends_on:
        dep_parts = [
            f"{dep_id} ({status_by_id.get(dep_id, TaskStatus.PENDING).value})"
            for dep_id in task.depends_on
        ]
        console.print(f"\n  [dim]Depends on: {', '.join(dep_parts)}[/dim]")

    if agent_context["present"]:
        file_list = ", ".join(entry["path"] for entry in agent_context["files"])
        console.print(f"\n  [dim]Agent context: {file_list}[/dim]")

    console.print(f"\n[bold]Action:[/bold]\n{task.action}")

    rp = state_mgr.get_resume_point()
    if rp and rp.failure_reason != "None":
        console.print(f"\n[yellow]Previous failure:[/yellow] {rp.failure_reason}")


def _load_next_context(
    project_path: Path,
) -> tuple[list[Phase], StateManager, dict[str, TaskStatus], list[TaskState], dict[str, Any]]:
    cfg = load_config(project_path)
    manager = ProjectManager(cfg)
    parser = MarkdownParser()

    if project_path.exists() and manager.has_any_required_files(project_path):
        missing = manager.missing_required_files(project_path)
        if missing:
            raise ValueError(f"Missing required files: {', '.join(missing)}")

    if not manager.is_sago_project(project_path):
        raise ValueError(f"Not a sago project: {project_path}")

    plan_file = project_path / "PLAN.md"
    if not plan_file.exists():
        raise ValueError("No PLAN.md found. Run `sago plan` first")

    phases = parser.parse_xml_tasks(plan_file.read_text(encoding="utf-8"))
    state_mgr = StateManager(project_path / "STATE.md")
    task_states = state_mgr.get_task_states(phases)
    status_by_id = {ts.task_id: ts.status for ts in task_states}
    agent_context = load_agent_context(project_path).to_summary_dict()
    return phases, state_mgr, status_by_id, task_states, agent_context


def _build_next_payload(project_path: Path) -> dict[str, Any]:
    from sago.validation import check_verify_safety

    phases, state_mgr, status_by_id, task_states, agent_context = _load_next_context(project_path)

    for phase in phases:
        for task in phase.tasks:
            if status_by_id.get(task.id) != TaskStatus.PENDING:
                continue
            if not _check_deps_met(task, phase, status_by_id):
                continue
            resume_point = state_mgr.get_resume_point()
            return {
                "success": True,
                "state": "task",
                "phase": phase.name,
                "task": task.to_dict(),
                "dependency_status": [
                    {"task_id": dep_id, "status": status_by_id.get(dep_id, TaskStatus.PENDING)}
                    for dep_id in task.depends_on
                ],
                "agent_context": agent_context,
                "verify_warnings": check_verify_safety(task.verify) if task.verify else [],
                "resume_point": resume_point.to_dict() if resume_point is not None else None,
            }

    if all(ts.status in {TaskStatus.DONE, TaskStatus.SKIPPED} for ts in task_states):
        return {
            "success": True,
            "state": "complete",
            "message": "All tasks complete!",
            "agent_context": agent_context,
        }

    failed = [ts for ts in task_states if ts.status == TaskStatus.FAILED]
    return {
        "success": True,
        "state": "blocked",
        "message": "No actionable tasks found.",
        "failed_tasks": len(failed),
        "agent_context": agent_context,
    }


def _do_next(project_path: Path) -> None:
    payload = _build_next_payload(project_path)
    if payload["state"] == "task":
        phases, state_mgr, status_by_id, _, agent_context = _load_next_context(project_path)
        task_data = payload["task"]
        for phase in phases:
            for task in phase.tasks:
                if task.id == task_data["id"]:
                    _print_next_task(task, phase, status_by_id, state_mgr, agent_context)
                    return
    elif payload["state"] == "complete":
        console.print("[green]All tasks complete![/green]")
    else:
        console.print("[yellow]No actionable tasks found.[/yellow]")
        if payload["failed_tasks"]:
            console.print(
                f"  {payload['failed_tasks']} task(s) failed — run `sago replan` to adjust the plan."
            )


@app.command(name="next")
def next_task(
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
    json_output: bool = typer.Option(False, "--json", help="Output structured JSON"),
) -> None:
    """Show the next task to work on.

    Reads PLAN.md and STATE.md, finds the first pending task whose dependencies
    are satisfied, and displays its full details including action and context.
    """
    try:
        if json_output:
            print_json_output(_build_next_payload(project_path))
            return
        _do_next(project_path)
    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            print_json_output({"success": False, "error": str(e)})
            raise typer.Exit(1) from None
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None
