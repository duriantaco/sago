"""sago status command."""

from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel
from rich.table import Table

from sago.commands import (
    app,
    console,
    get_phase_gates,
    get_phase_status,
    load_config,
    print_json_output,
    serialize_state_for_builder,
    show_recommendations,
    summarize_evidence,
    summarize_memory,
)
from sago.core.parser import MarkdownParser
from sago.core.project import ProjectManager
from sago.models import Phase
from sago.models.execution import ExecutionHistory
from sago.models.plan import Plan
from sago.models.state import ProjectState, TaskState, TaskStatus
from sago.persistence import ExecutionHistoryStore
from sago.recommendations import RecommendationEngine
from sago.state import StateManager
from sago.utils.agent_context import load_agent_context


def _show_task_progress(phases: list[Phase], task_states: list[TaskState], detailed: bool) -> None:
    """Display task progress summary and optional per-phase breakdown."""
    completed_set = {ts.task_id for ts in task_states if ts.status == TaskStatus.DONE}
    failed_set = {ts.task_id for ts in task_states if ts.status == TaskStatus.FAILED}
    skipped_set = {ts.task_id for ts in task_states if ts.status == TaskStatus.SKIPPED}
    total_tasks = sum(len(phase.tasks) for phase in phases)
    console.print("\n[bold]Task Progress:[/bold]")
    console.print(f"   Done: {len(completed_set)}/{total_tasks} tasks")
    if failed_set or skipped_set:
        console.print(f"   Failed: {len(failed_set)}   Skipped: {len(skipped_set)}")

    if not detailed:
        return

    console.print("\n[bold]Phases:[/bold]")
    for phase in phases:
        phase_completed = sum(1 for t in phase.tasks if t.id in completed_set)
        console.print(f"\n   {phase.name} ({phase_completed}/{len(phase.tasks)})")
        for task in phase.tasks:
            if task.id in completed_set:
                style = "[green]"
            elif task.id in failed_set:
                style = "[red]"
            elif task.id in skipped_set:
                style = "[yellow]"
            else:
                style = "[dim]"
            console.print(f"      {style}{task.id}: {task.name}[/{style.strip('[')}]")


def _show_status_overview(
    info: dict[str, Any],
    state: ProjectState | None,
) -> None:
    """Print project status header table."""
    console.print(Panel(f"[bold]{info['name']}[/bold]", title="Project Status"))
    table = Table(show_header=False)
    table.add_row(
        "[cyan]Active Phase[/cyan]",
        state.active_phase or "Unknown" if state else "Unknown",
    )
    table.add_row(
        "[cyan]Current Task[/cyan]",
        state.current_task or "Unknown" if state else "Unknown",
    )
    table.add_row("[cyan]Path[/cyan]", str(info["path"]))
    console.print(table)


def _show_resume_point(state: ProjectState) -> None:
    """Print resume point table if one exists."""
    if state.resume_point is None:
        return
    rp = state.resume_point
    rp_table = Table(title="Resume Point", show_header=False)
    rp_table.add_row("[green]Last Completed[/green]", rp.last_completed)
    rp_table.add_row("[yellow]Next Task[/yellow]", rp.next_task)
    rp_table.add_row("[yellow]Next Action[/yellow]", rp.next_action)
    if rp.failure_reason != "None":
        rp_table.add_row("[red]Failure Reason[/red]", rp.failure_reason)
    rp_table.add_row("[cyan]Checkpoint[/cyan]", rp.checkpoint)
    console.print(rp_table)


def _show_agent_context(agent_context: dict[str, Any]) -> None:
    """Print detected repo-local agent context files."""
    if not agent_context["present"]:
        return

    filenames = ", ".join(entry["path"] for entry in agent_context["files"])
    console.print(f"\n[bold]Agent Context:[/bold] {filenames}")


def _show_status_next_steps(has_plan: bool) -> None:
    """Print next-steps guidance based on whether a plan exists."""
    if has_plan:
        console.print("\n[bold]Next steps:[/bold]")
        console.print("   Point your coding agent at this project")
        console.print("   Claude Code reads CLAUDE.md automatically")
        console.print("   sago status -d   - Detailed task status")
    else:
        console.print("\n[bold]Next Steps:[/bold]")
        console.print("   1. Edit REQUIREMENTS.md")
        console.print("   2. Run: sago plan")


def _load_status_context(
    project_path: Path,
) -> tuple[
    dict[str, Any],
    list[Phase],
    ProjectState | None,
    str | None,
    dict[str, Any],
    ExecutionHistory | None,
]:
    cfg = load_config(project_path)
    manager = ProjectManager(cfg)
    parser = MarkdownParser()

    if project_path.exists() and manager.has_any_required_files(project_path):
        missing = manager.missing_required_files(project_path)
        if missing:
            raise ValueError(f"Missing required files: {', '.join(missing)}")

    if not manager.is_sago_project(project_path):
        raise ValueError(f"Not a sago project: {project_path}")

    info = manager.get_project_info(project_path)
    agent_context = load_agent_context(project_path).to_summary_dict()
    state_mgr = StateManager(project_path / "STATE.md")
    execution_history = ExecutionHistoryStore(project_path).load()

    plan_file = project_path / "PLAN.md"
    phases: list[Phase] = []
    plan_error: str | None = None
    if plan_file.exists():
        try:
            phases = parser.parse_xml_tasks(plan_file.read_text(encoding="utf-8"))
        except Exception as e:
            plan_error = str(e)

    state = state_mgr.get_project_state(phases) if phases else None
    return info, phases, state, plan_error, agent_context, execution_history


def _build_status_payload(
    info: dict[str, Any],
    phases: list[Phase],
    state: ProjectState | None,
    plan_error: str | None,
    agent_context: dict[str, Any],
    execution_history: ExecutionHistory | None,
) -> dict[str, Any]:
    has_plan = bool(phases)
    task_states = state.task_states if state else []
    task_summary = {
        "completed": sum(1 for ts in task_states if ts.status == TaskStatus.DONE),
        "failed": sum(1 for ts in task_states if ts.status == TaskStatus.FAILED),
        "pending": sum(1 for ts in task_states if ts.status == TaskStatus.PENDING),
        "skipped": sum(1 for ts in task_states if ts.status == TaskStatus.SKIPPED),
        "total": len(task_states),
    }

    recommendations: list[dict[str, Any]] = []
    if phases and state:
        recs = RecommendationEngine().evaluate(
            plan=Plan(phases=phases),
            state=state,
            execution_history=execution_history,
        )
        recommendations = [rec.model_dump() for rec in recs]

    return {
        "success": True,
        "project": info,
        "agent_context": agent_context,
        "has_plan": has_plan,
        "plan_error": plan_error,
        "state": serialize_state_for_builder(state),
        "task_summary": task_summary,
        "evidence_summary": summarize_evidence(state, execution_history),
        "memory_summary": summarize_memory(state),
        "phases": get_phase_status(phases, task_states) if phases and state else [],
        "phase_gates": get_phase_gates(phases, state) if phases and state else [],
        "recommendations": recommendations,
        "blockers": state.blockers if state else [],
        "next_steps": (
            [
                "Point your coding agent at this project",
                "Read repo-local agent instructions such as IMPORTANT.md, AGENTS.md, or CLAUDE.md",
                "sago status -d - Detailed task status",
            ]
            if has_plan
            else ["Edit REQUIREMENTS.md", "Run: sago plan"]
        ),
    }


def _do_status(project_path: Path, detailed: bool) -> None:
    info, phases, state, plan_error, agent_context, execution_history = _load_status_context(
        project_path
    )

    _show_status_overview(info, state)
    _show_agent_context(agent_context)

    if plan_error is not None:
        console.print(f"\n[yellow]Could not parse PLAN.md: {plan_error}[/yellow]")

    if state:
        _show_resume_point(state)

    if phases and state:
        _show_task_progress(phases, state.task_states, detailed)
        phase_gates = get_phase_gates(phases, state)
        if phase_gates:
            console.print("\n[bold]Phase Gates:[/bold]")
            for gate in phase_gates:
                style = {"approved": "green", "pending_review": "yellow", "blocked": "red"}[
                    gate["status"]
                ]
                console.print(f"  [{style}]{gate['phase_name']}: {gate['status']}[/{style}]")
        show_recommendations(
            phases,
            state.task_states,
            execution_history,
            phase_reviews=state.phase_reviews,
        )

    if state and state.blockers:
        console.print("\n[yellow]Known Blockers:[/yellow]")
        for blocker in state.blockers:
            console.print(f"  - {blocker}")

    _show_status_next_steps(bool(phases))


@app.command()
def status(
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
    detailed: bool = typer.Option(False, "--detailed", "-d", help="Show detailed task status"),
    json_output: bool = typer.Option(False, "--json", help="Output structured JSON"),
) -> None:
    try:
        info, phases, state, plan_error, agent_context, execution_history = _load_status_context(
            project_path
        )
        if json_output:
            print_json_output(
                _build_status_payload(
                    info,
                    phases,
                    state,
                    plan_error,
                    agent_context,
                    execution_history,
                )
            )
            return
        _do_status(project_path, detailed)
    except Exception as e:
        if json_output:
            print_json_output({"success": False, "error": str(e)})
            raise typer.Exit(1) from None
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None
