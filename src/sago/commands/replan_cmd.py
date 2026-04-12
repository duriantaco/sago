"""sago replan command."""

import asyncio
from pathlib import Path
from typing import Any

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from sago.agents.orchestrator import PlanningWorkflow
from sago.commands import (
    app,
    check_llm_configured,
    console,
    get_phase_status,
    load_config,
    show_plan_summary,
    show_recommendations,
    show_validation_results,
)
from sago.core.parser import MarkdownParser
from sago.core.project import ProjectManager
from sago.models import Phase
from sago.models.state import TaskState, TaskStatus
from sago.state import StateManager


def _write_phase_summary_to_state(state_file: Path, phase_name: str, review_output: str) -> None:
    """Append a phase summary to STATE.md (skips if already present)."""
    state_mgr = StateManager(state_file)
    state_mgr.append_phase_summary(phase_name, review_output)


def _show_plan_diff(old_phases: list[Phase], new_phases: list[Phase]) -> None:
    """Show added/modified/removed tasks between old and new plan."""
    old_task_ids = {t.id for p in old_phases for t in p.tasks}
    new_task_ids = {t.id for p in new_phases for t in p.tasks}
    old_tasks_by_id = {t.id: t for p in old_phases for t in p.tasks}
    new_tasks_by_id = {t.id: t for p in new_phases for t in p.tasks}

    added = new_task_ids - old_task_ids
    removed = old_task_ids - new_task_ids
    modified = set()
    for tid in old_task_ids & new_task_ids:
        old_t = old_tasks_by_id[tid]
        new_t = new_tasks_by_id[tid]
        if (
            old_t.name != new_t.name
            or old_t.action != new_t.action
            or old_t.files != new_t.files
            or old_t.verify != new_t.verify
            or old_t.depends_on != new_t.depends_on
        ):
            modified.add(tid)

    console.print(
        f"\n[bold]Changes:[/bold] "
        f"[green]+{len(added)} added[/green], "
        f"[yellow]~{len(modified)} modified[/yellow], "
        f"[red]-{len(removed)} removed[/red]"
    )

    if added:
        for tid in sorted(added):
            console.print(f"  [green]+ {tid}: {new_tasks_by_id[tid].name}[/green]")
    if modified:
        for tid in sorted(modified):
            console.print(f"  [yellow]~ {tid}: {new_tasks_by_id[tid].name}[/yellow]")
    if removed:
        for tid in sorted(removed):
            console.print(f"  [red]- {tid}: {old_tasks_by_id[tid].name}[/red]")


def _show_replan_status(
    task_states: list[TaskState],
    phase_statuses: list[dict[str, Any]],
) -> None:
    """Print current plan status summary for replan."""
    done_count = sum(1 for ts in task_states if ts.status == TaskStatus.DONE)
    failed_count = sum(1 for ts in task_states if ts.status == TaskStatus.FAILED)
    pending_count = sum(1 for ts in task_states if ts.status == TaskStatus.PENDING)
    skipped_count = sum(1 for ts in task_states if ts.status == TaskStatus.SKIPPED)
    total = done_count + failed_count + pending_count + skipped_count

    console.print(
        f"\n[bold]Current plan:[/bold] {total} tasks — "
        f"[green]{done_count} done[/green], "
        f"[red]{failed_count} failed[/red], "
        f"[yellow]{skipped_count} skipped[/yellow], "
        f"[dim]{pending_count} pending[/dim]"
    )

    for ps in phase_statuses:
        if ps["status"] == "complete":
            icon = "[green]✓[/green]"
        elif ps["status"] == "partial":
            icon = "[yellow]~[/yellow]"
        else:
            icon = "[dim]..[/dim]"
        console.print(f"   {icon} {ps['name']} ({ps['done']}/{ps['total']} done)")


def _review_phases(
    project_path: Path,
    old_phases: list[Phase],
    phase_statuses: list[dict[str, Any]],
    state_file: Path,
    review_prompt: str,
    orchestrator: PlanningWorkflow,
) -> list[str]:
    """Review completed phases that haven't been reviewed yet."""
    from rich.panel import Panel

    existing_state = state_file.read_text(encoding="utf-8") if state_file.exists() else ""
    review_outputs: list[str] = []

    for i, ps in enumerate(phase_statuses):
        if ps["status"] != "complete":
            continue
        summary_header = f"## Phase Summary: {ps['name']}"
        if summary_header in existing_state:
            continue

        phase = old_phases[i]
        console.print(f"\nReviewing {ps['name']}...")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task(description=f"Reviewing {ps['name']}...", total=None)
            review_result = asyncio.run(orchestrator.run_review(project_path, phase, review_prompt))

        if review_result.success:
            review_text = review_result.output
            review_outputs.append(review_text)
            console.print(Panel(review_text, title=f"Review: {ps['name']}", border_style="cyan"))
            _write_phase_summary_to_state(state_file, ps["name"], review_text)
        else:
            console.print(f"[yellow]Review failed for {ps['name']}: {review_result.error}[/yellow]")

    return review_outputs


def _execute_replan(
    project_path: Path,
    old_phases: list[Phase],
    feedback: str,
    review_outputs: list[str],
    orchestrator: PlanningWorkflow,
    auto_apply: bool,
) -> None:
    """Run the replan workflow, show diff, and prompt for confirmation."""
    from sago.utils.repo_map import generate_repo_map

    plan_file = project_path / "PLAN.md"
    parser = MarkdownParser()
    combined_review = "\n\n".join(review_outputs) if review_outputs else ""
    repo_map = generate_repo_map(project_path)
    old_plan_backup = plan_file.read_text(encoding="utf-8")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(description="Updating plan...", total=None)
        result = asyncio.run(
            orchestrator.run_replan_workflow(
                project_path=project_path,
                feedback=feedback,
                review_context=combined_review,
                repo_map=repo_map,
            )
        )

    if not result.success:
        console.print(f"[red]Replan failed: {result.error}[/red]")
        raise typer.Exit(1)

    new_content = plan_file.read_text(encoding="utf-8")
    new_phases = parser.parse_xml_tasks(new_content)

    _show_plan_diff(old_phases, new_phases)
    show_validation_results(new_phases)

    if not auto_apply and not typer.confirm("\nApply changes?"):
        plan_file.write_text(old_plan_backup, encoding="utf-8")
        console.print("[dim]Changes reverted.[/dim]")
        raise typer.Exit(0)

    console.print("\n[green]Plan updated successfully![/green]")
    show_plan_summary(project_path)


def _do_replan(
    project_path: Path,
    feedback: str | None = None,
    auto_apply: bool = False,
) -> None:
    cfg = load_config(project_path)
    manager = ProjectManager(cfg)
    parser = MarkdownParser()

    if project_path.exists() and manager.has_any_required_files(project_path):
        missing = manager.missing_required_files(project_path)
        if missing:
            console.print(f"[red]Missing required files: {', '.join(missing)}[/red]")
            console.print("[yellow]Run 'sago init' first[/yellow]")
            raise typer.Exit(1)

    if not manager.is_sago_project(project_path):
        console.print(f"[red]Not a sago project: {project_path}[/red]")
        console.print("[yellow]Run 'sago init' first[/yellow]")
        raise typer.Exit(1)

    check_llm_configured(cfg)

    plan_file = project_path / "PLAN.md"
    if not plan_file.exists():
        console.print("[red]No PLAN.md found.[/red]")
        console.print("[yellow]Run `sago plan` first[/yellow]")
        raise typer.Exit(1)

    plan_content = plan_file.read_text(encoding="utf-8")
    old_phases = parser.parse_xml_tasks(plan_content)

    state_file = project_path / "STATE.md"
    state_mgr = StateManager(state_file)
    task_states = state_mgr.get_task_states(old_phases)

    phase_statuses = get_phase_status(old_phases, task_states)
    _show_replan_status(task_states, phase_statuses)

    review_prompt = parser.parse_review_prompt(plan_content)
    if not review_prompt:
        review_prompt = (
            "Review each completed task for: code correctness, adherence to requirements, "
            "edge-case handling, security issues, and consistency with the project style."
        )

    orchestrator = PlanningWorkflow(config=cfg)
    review_outputs = _review_phases(
        project_path,
        old_phases,
        phase_statuses,
        state_file,
        review_prompt,
        orchestrator,
    )

    show_recommendations(old_phases, task_states)

    if feedback is None:
        feedback = typer.prompt(
            "\nWhat do you want to change? (Enter to skip)",
            default="",
        )

    if not feedback:
        if review_outputs:
            console.print("[green]Phase review saved to STATE.md. No plan changes.[/green]")
        else:
            console.print("[dim]No changes.[/dim]")
        return

    _execute_replan(
        project_path,
        old_phases,
        feedback,
        review_outputs,
        orchestrator,
        auto_apply,
    )


@app.command()
def replan(
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
    feedback: str | None = typer.Option(
        None, "--feedback", "-f", help="Feedback to apply (skips interactive prompt)"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-apply changes without confirmation"),
) -> None:
    """Update PLAN.md based on your feedback without regenerating from scratch."""
    try:
        _do_replan(project_path, feedback=feedback, auto_apply=yes)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None
