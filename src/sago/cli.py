import asyncio
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from sago.agents.orchestrator import Orchestrator
from sago.core.config import Config, find_dotenv
from sago.core.parser import MarkdownParser
from sago.core.project import ProjectManager
from sago.models import Phase
from sago.models.plan import Plan
from sago.models.state import ProjectState, TaskState, TaskStatus
from sago.recommendations import RecommendationEngine
from sago.state import StateManager
from sago.validation import PlanValidator

app = typer.Typer(
    name="sago",
    help="sago - AI project planning for coding agents",
    add_completion=False,
)

console = Console()
config = Config()


def _load_config(project_path: Path | None = None) -> Config:
    """Reload Config, searching for .env from *project_path* upwards."""
    global config
    if project_path is not None:
        env_file = find_dotenv(project_path) or ".env"
        config = Config(_env_file=env_file)  # type: ignore[call-arg]
    return config


# Provider-specific env vars that litellm checks automatically
_PROVIDER_KEY_ENV_VARS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "azure": "AZURE_API_KEY",
    "cohere": "COHERE_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY",
    "together_ai": "TOGETHERAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}


def _check_llm_configured() -> None:
    """Fail early if no LLM API key is available."""
    if config.llm_api_key:
        return
    if config.is_chatgpt_subscription:
        return
    provider_env = _PROVIDER_KEY_ENV_VARS.get(config.llm_provider, "")
    console.print(
        Panel(
            f"[bold red]No API key configured for LLM provider '{config.llm_provider}'[/bold red]\n\n"
            "Set one of the following in your .env file:\n"
            f"  [cyan]LLM_API_KEY=sk-...[/cyan]\n"
            + (f"  [cyan]{provider_env}=sk-...[/cyan]\n" if provider_env else "")
            + "\nOr export it in your environment:\n"
            "  export LLM_API_KEY=sk-..."
            + (f"\n  export {provider_env}=sk-..." if provider_env else ""),
            title="Missing API Key",
            border_style="red",
        )
    )
    raise typer.Exit(1)


# Distinctive strings from the placeholder templates
_PLACEHOLDER_MARKERS = [
    "A brief description of what you're building and why",
    "TaskFlow is a CLI task runner",
    "Each requirement becomes one or more tasks in the plan",
    "Parse YAML job files with `name`, `command`, `depends_on`",
]


def _check_placeholder_content(project_path: Path) -> None:
    """Warn if PROJECT.md / REQUIREMENTS.md still contain placeholder template content."""
    files_with_placeholders: list[str] = []
    for filename in ["PROJECT.md", "REQUIREMENTS.md"]:
        filepath = project_path / filename
        if not filepath.exists():
            continue
        content = filepath.read_text(encoding="utf-8")
        if any(marker in content for marker in _PLACEHOLDER_MARKERS):
            files_with_placeholders.append(filename)

    if not files_with_placeholders:
        return

    console.print(
        Panel(
            "[bold yellow]The following files still contain placeholder/example content:[/bold yellow]\n"
            + "".join(f"  - {f}\n" for f in files_with_placeholders)
            + "\nThe planner will generate a plan based on whatever is in these files.\n"
            "If you haven't edited them, you'll get a plan for the example project, "
            "not yours.",
            title="Placeholder Content Detected",
            border_style="yellow",
        )
    )
    if not typer.confirm("Continue anyway?"):
        console.print("[dim]Edit your PROJECT.md and REQUIREMENTS.md, then re-run.[/dim]")
        raise typer.Exit(0)


def _show_recommendations(phases: list[Phase], task_states: list[TaskState]) -> None:
    """Evaluate and display recommendations based on plan + state."""
    plan = Plan(phases=phases)
    state = ProjectState(task_states=task_states)
    engine = RecommendationEngine()
    recs = engine.evaluate(plan, state)

    if not recs:
        return

    style_map = {
        "suggest_replan": "yellow",
        "warn_repeated_failure": "red",
        "warn_scope_drift": "red",
        "suggest_review": "cyan",
        "warn_invalid_verify": "yellow",
        "warn_missing_tests": "yellow",
        "phase_complete": "green",
    }

    console.print("\n[bold]Recommendations:[/bold]")
    for rec in recs:
        style = style_map.get(rec.type, "dim")
        console.print(f"  [{style}]{rec.message}[/{style}]")


def _show_validation_results(phases: list[Phase]) -> bool:
    """Validate plan and display results. Returns True if plan is valid (no errors)."""
    plan = Plan(phases=phases)
    validator = PlanValidator()
    result = validator.validate(plan)

    if not result.issues:
        console.print("[green]Validation: no issues found[/green]")
        return True

    style_map = {"error": "red", "warning": "yellow", "suggestion": "blue"}
    console.print("\n[bold]Validation Results:[/bold]")
    for issue in result.issues:
        style = style_map.get(issue.severity, "dim")
        label = issue.severity.upper()
        loc = ""
        if issue.task_id:
            loc = f" (task {issue.task_id})"
        elif issue.phase_name:
            loc = f" ({issue.phase_name})"
        console.print(f"  [{style}]{label}[/{style}]{loc}: {issue.message}")

    error_count = len(result.errors)
    warn_count = len(result.warnings)
    sug_count = len(result.suggestions)
    console.print(f"  {error_count} error(s), {warn_count} warning(s), {sug_count} suggestion(s)")

    return result.valid


def _do_init(
    project_name: str | None,
    path: Path | None,
    overwrite: bool,
    prompt: str | None = None,
    yes: bool = False,
) -> None:
    is_tty = console.is_terminal

    # Interactive flow: no name provided and we're in a terminal
    if not project_name and not yes and is_tty:
        default_name = (path or Path.cwd()).name if path else "my-project"
        console.print("[bold blue]sago Project Initialization[/bold blue]\n")
        project_name = typer.prompt("Project name", default=default_name)

        if not prompt:
            description = typer.prompt(
                "Describe what you want to build (or press Enter to skip)",
                default="",
            )
            if description:
                prompt = description

    if not project_name:
        console.print("[red]Project name is required. Pass a name or use interactive mode.[/red]")
        raise typer.Exit(1)

    project_path = path or Path.cwd() / project_name
    manager = ProjectManager(config)
    manager.init_project(project_path, project_name=project_name, overwrite=overwrite)

    prompt_succeeded = False
    if prompt:
        console.print("[dim]Generating project files from prompt...[/dim]")
        try:
            _check_llm_configured()
            asyncio.run(manager.generate_from_prompt(prompt, project_path, project_name))
            console.print("[green]Generated PROJECT.md and REQUIREMENTS.md from prompt[/green]")
            prompt_succeeded = True
        except typer.Exit:
            raise
        except Exception as e:
            console.print(
                Panel(
                    f"[bold red]Failed to generate project files from your prompt.[/bold red]\n\n"
                    f"Error: {e}\n\n"
                    "[yellow]Your description was NOT used.[/yellow]\n"
                    "The project files contain placeholder examples, not your project.\n"
                    "You need to either:\n"
                    "  1. Configure an LLM API key and re-run [cyan]sago init[/cyan]\n"
                    "  2. Manually edit PROJECT.md and REQUIREMENTS.md",
                    title="Prompt Generation Failed",
                    border_style="red",
                )
            )

    console.print(f"\n[green]Project initialized at: {project_path}[/green]")
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. cd " + str(project_path))
    if prompt_succeeded:
        console.print("  2. Run: sago plan")
        console.print("  3. Point your coding agent at the project (it reads CLAUDE.md)")
    else:
        console.print("  2. Edit PROJECT.md and REQUIREMENTS.md")
        console.print("  3. Run: sago plan")
        console.print("  4. Point your coding agent at the project (it reads CLAUDE.md)")


@app.command()
def init(
    project_name: str | None = typer.Argument(None, help="Project name"),
    path: Path | None = typer.Option(None, "--path", "-p", help="Project path"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing files"),
    prompt: str | None = typer.Option(
        None, "--prompt", help="Generate project files from a one-line description"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive mode, accept defaults"),
) -> None:
    """Initialize a new sago project.

    When run without a project name, prompts interactively for the name and
    an optional description.  Pass --yes / -y to skip all prompts.
    """
    try:
        _do_init(project_name, path, overwrite, prompt=prompt, yes=yes)
    except FileExistsError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def _show_task_progress(phases: list[Phase], task_states: list[TaskState], detailed: bool) -> None:
    """Display task progress summary and optional per-phase breakdown."""
    completed_set = {ts.task_id for ts in task_states if ts.status == TaskStatus.DONE}
    failed_set = {ts.task_id for ts in task_states if ts.status == TaskStatus.FAILED}
    total_tasks = sum(len(phase.tasks) for phase in phases)
    console.print("\n[bold]Task Progress:[/bold]")
    console.print(f"   Completed: {len(completed_set)}/{total_tasks} tasks")

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
            else:
                style = "[dim]"
            console.print(f"      {style}{task.id}: {task.name}[/{style.strip('[')}]")


def _show_plan_summary(project_path: Path) -> list[str]:
    """Read PLAN.md, display phase/task summary and dependencies. Returns dependency list."""
    parser = MarkdownParser()
    plan_file = project_path / "PLAN.md"
    content = plan_file.read_text(encoding="utf-8")

    phases = parser.parse_xml_tasks(content)
    dependencies = parser.parse_dependencies(content)

    # Phase/task table
    table = Table(title="Plan Summary", show_header=True)
    table.add_column("Phase", style="cyan")
    table.add_column("Task ID", style="dim")
    table.add_column("Task Name")

    for phase in phases:
        for i, task in enumerate(phase.tasks):
            phase_label = phase.name if i == 0 else ""
            table.add_row(phase_label, task.id, task.name)

    console.print(table)

    total_tasks = sum(len(p.tasks) for p in phases)
    console.print(f"\n   [bold]{len(phases)}[/bold] phases, [bold]{total_tasks}[/bold] tasks")

    # Dependencies panel
    if dependencies:
        dep_text = "\n".join(f"  - {dep}" for dep in dependencies)
        console.print(Panel(dep_text, title="Dependencies", border_style="blue"))

    return dependencies


def _do_status(project_path: Path, detailed: bool) -> None:
    _load_config(project_path)
    manager = ProjectManager(config)
    parser = MarkdownParser()

    if not manager.is_sago_project(project_path):
        console.print(f"[red]Not a sago project: {project_path}[/red]")
        raise typer.Exit(1)

    info = manager.get_project_info(project_path)
    state_mgr = StateManager(project_path / "STATE.md")

    # We need plan phases for full state parsing
    plan_file = project_path / "PLAN.md"
    phases: list[Phase] = []
    if plan_file.exists():
        try:
            phases = parser.parse_xml_tasks(plan_file.read_text(encoding="utf-8"))
        except Exception as e:
            console.print(f"\n[yellow]Could not parse PLAN.md: {e}[/yellow]")

    state = state_mgr.get_project_state(phases) if phases else None

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

    if state and state.resume_point is not None:
        rp = state.resume_point
        rp_table = Table(title="Resume Point", show_header=False)
        rp_table.add_row("[green]Last Completed[/green]", rp.last_completed)
        rp_table.add_row("[yellow]Next Task[/yellow]", rp.next_task)
        rp_table.add_row("[yellow]Next Action[/yellow]", rp.next_action)
        if rp.failure_reason != "None":
            rp_table.add_row("[red]Failure Reason[/red]", rp.failure_reason)
        rp_table.add_row("[cyan]Checkpoint[/cyan]", rp.checkpoint)
        console.print(rp_table)

    if phases and state:
        _show_task_progress(phases, state.task_states, detailed)
        _show_recommendations(phases, state.task_states)

    if state and state.blockers:
        console.print("\n[yellow]Known Blockers:[/yellow]")
        for blocker in state.blockers:
            console.print(f"  - {blocker}")

    if plan_file.exists():
        console.print("\n[bold]Next steps:[/bold]")
        console.print("   Point your coding agent at this project")
        console.print("   Claude Code reads CLAUDE.md automatically")
        console.print("   sago status -d   - Detailed task status")
    else:
        console.print("\n[bold]Next Steps:[/bold]")
        console.print("   1. Edit REQUIREMENTS.md")
        console.print("   2. Run: sago plan")


@app.command()
def status(
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
    detailed: bool = typer.Option(False, "--detailed", "-d", help="Show detailed task status"),
) -> None:
    try:
        _do_status(project_path, detailed)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def _do_plan(project_path: Path, force: bool, auto_accept: bool = False) -> None:
    _load_config(project_path)
    manager = ProjectManager(config)

    if not manager.is_sago_project(project_path):
        console.print(f"[red]Not a sago project: {project_path}[/red]")
        console.print("[yellow]Run 'sago init' first[/yellow]")
        raise typer.Exit(1)

    _check_llm_configured()

    plan_file = project_path / "PLAN.md"
    old_plan_backup = None
    if plan_file.exists():
        if not force:
            console.print("[yellow]PLAN.md already exists[/yellow]")
            if not typer.confirm("Overwrite?"):
                raise typer.Exit(0)
        old_plan_backup = plan_file.read_text(encoding="utf-8")

    required_files = ["PROJECT.md", "REQUIREMENTS.md"]
    missing = [f for f in required_files if not (project_path / f).exists()]
    if missing:
        console.print(f"[red]Missing required files: {', '.join(missing)}[/red]")
        raise typer.Exit(1)

    _check_placeholder_content(project_path)

    orchestrator = Orchestrator(config=config)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(description="Generating plan...", total=None)
        result = asyncio.run(
            orchestrator.run_workflow(
                project_path=project_path,
                plan=True,
            )
        )

    if result.success:
        console.print("\n[green]Plan generated successfully![/green]")
        console.print(f"   {plan_file}\n")

        _show_plan_summary(project_path)

        # Show validation results (approval gate)
        parser = MarkdownParser()
        try:
            phases = parser.parse_xml_tasks(plan_file.read_text(encoding="utf-8"))
            _show_validation_results(phases)

            if not auto_accept:
                if not typer.confirm("\nAccept this plan?", default=True):
                    if old_plan_backup is not None:
                        plan_file.write_text(old_plan_backup, encoding="utf-8")
                        console.print("[dim]Plan reverted to previous version.[/dim]")
                    else:
                        plan_file.unlink()
                        console.print("[dim]Plan rejected and removed.[/dim]")
                    raise typer.Exit(0)
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[yellow]Could not validate plan: {e}[/yellow]")

        console.print("\n[bold]Next steps:[/bold]")
        console.print("   1. Review PLAN.md")
        console.print("   2. Point your coding agent at the project")
        console.print("      Claude Code reads CLAUDE.md automatically")
    else:
        console.print(f"[red]Plan generation failed: {result.error}[/red]")
        raise typer.Exit(1)


@app.command()
def plan(
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing PLAN.md"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-accept plan without confirmation"),
) -> None:
    """Generate PLAN.md from requirements and project context."""
    try:
        _do_plan(project_path, force, auto_accept=yes)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def _get_phase_status(phases: list[Phase], task_states: list[TaskState]) -> list[dict[str, Any]]:
    """Group task states by phase, returning per-phase status.

    Returns list of dicts: {name, done, failed, pending, total, status}
    where status is 'complete', 'partial', or 'pending'.
    """
    state_by_id = {ts.task_id: ts.status.value for ts in task_states}
    result: list[dict[str, Any]] = []
    for phase in phases:
        done = sum(1 for t in phase.tasks if state_by_id.get(t.id) == "done")
        failed = sum(1 for t in phase.tasks if state_by_id.get(t.id) == "failed")
        pending = len(phase.tasks) - done - failed
        if done == len(phase.tasks):
            status = "complete"
        elif done > 0 or failed > 0:
            status = "partial"
        else:
            status = "pending"
        result.append(
            {
                "name": phase.name,
                "done": done,
                "failed": failed,
                "pending": pending,
                "total": len(phase.tasks),
                "status": status,
            }
        )
    return result


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


def _do_replan(
    project_path: Path,
    feedback: str | None = None,
    auto_apply: bool = False,
) -> None:
    _load_config(project_path)
    manager = ProjectManager(config)
    parser = MarkdownParser()

    if not manager.is_sago_project(project_path):
        console.print(f"[red]Not a sago project: {project_path}[/red]")
        console.print("[yellow]Run 'sago init' first[/yellow]")
        raise typer.Exit(1)

    _check_llm_configured()

    plan_file = project_path / "PLAN.md"
    if not plan_file.exists():
        console.print("[red]No PLAN.md found.[/red]")
        console.print("[yellow]Run `sago plan` first[/yellow]")
        raise typer.Exit(1)

    plan_content = plan_file.read_text(encoding="utf-8")
    old_phases = parser.parse_xml_tasks(plan_content)

    # Parse STATE.md for current status via StateManager
    state_file = project_path / "STATE.md"
    state_mgr = StateManager(state_file)
    task_states = state_mgr.get_task_states(old_phases)

    done_count = sum(1 for ts in task_states if ts.status == TaskStatus.DONE)
    failed_count = sum(1 for ts in task_states if ts.status == TaskStatus.FAILED)
    pending_count = sum(1 for ts in task_states if ts.status == TaskStatus.PENDING)
    total = done_count + failed_count + pending_count

    # Show per-phase breakdown
    phase_statuses = _get_phase_status(old_phases, task_states)

    console.print(
        f"\n[bold]Current plan:[/bold] {total} tasks — "
        f"[green]{done_count} done[/green], "
        f"[red]{failed_count} failed[/red], "
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

    # Review completed/partial phases that haven't been reviewed yet
    review_prompt = parser.parse_review_prompt(plan_content)
    if not review_prompt:
        review_prompt = (
            "Review each completed task for: code correctness, adherence to requirements, "
            "edge-case handling, security issues, and consistency with the project style."
        )

    orchestrator = Orchestrator(config=config)
    review_outputs: list[str] = []

    existing_state = state_file.read_text(encoding="utf-8") if state_file.exists() else ""

    for i, ps in enumerate(phase_statuses):
        if ps["status"] == "pending":
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

    # Show recommendations before feedback prompt
    _show_recommendations(old_phases, task_states)

    # Prompt for feedback (skip if provided via --feedback)
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

    # Full replan with review context + repo map
    combined_review = "\n\n".join(review_outputs) if review_outputs else ""

    from sago.utils.repo_map import generate_repo_map

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

    # Parse new plan and show diff + validation
    new_content = plan_file.read_text(encoding="utf-8")
    new_phases = parser.parse_xml_tasks(new_content)

    _show_plan_diff(old_phases, new_phases)
    _show_validation_results(new_phases)

    if not auto_apply and not typer.confirm("\nApply changes?"):
        plan_file.write_text(old_plan_backup, encoding="utf-8")
        console.print("[dim]Changes reverted.[/dim]")
        raise typer.Exit(0)

    console.print("\n[green]Plan updated successfully![/green]")
    _show_plan_summary(project_path)


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
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def _do_watch(project_path: Path, port: int) -> None:
    import time

    from sago.web.server import start_watch_server
    from sago.web.watcher import ProjectWatcher

    _load_config(project_path)
    manager = ProjectManager(config)
    parser = MarkdownParser()

    if not manager.is_sago_project(project_path):
        console.print(f"[red]Not a sago project: {project_path}[/red]")
        raise typer.Exit(1)

    plan_file = project_path / "PLAN.md"
    if not plan_file.exists():
        console.print("[red]No PLAN.md found.[/red]")
        console.print("[yellow]Run `sago plan` first[/yellow]")
        raise typer.Exit(1)

    content = plan_file.read_text(encoding="utf-8")
    phases = parser.parse_xml_tasks(content)
    dependencies = parser.parse_dependencies(content)

    plan_data = {
        "project_name": project_path.name,
        "phases": [p.to_dict() for p in phases],
        "dependencies": dependencies,
    }

    trace_path = project_path / config.planning_dir / "trace.jsonl"

    watcher = ProjectWatcher(project_path=project_path, plan_phases=phases)
    server = start_watch_server(
        project_path=project_path,
        watcher=watcher,
        plan_data=plan_data,
        trace_path=trace_path,
        port=port,
        open_browser=True,
    )

    url = f"http://127.0.0.1:{server.server_address[1]}"
    console.print(f"[green]sago watch running at {url}[/green]")
    console.print("[dim]Press Ctrl+C to stop[/dim]")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()
        console.print("\n[dim]Stopped[/dim]")


@app.command()
def watch(
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
    port: int = typer.Option(0, "--port", help="Server port (0=auto)"),
) -> None:
    """Launch mission control to monitor coding agent progress."""
    try:
        _do_watch(project_path, port)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


_JUDGE_MODELS: list[tuple[str, str]] = [
    ("gpt-4o", "OpenAI"),
    ("gpt-4o-mini", "OpenAI"),
    ("claude-sonnet-4-20250514", "Anthropic"),
    ("claude-haiku-4-5-20251001", "Anthropic"),
    ("gemini/gemini-2.0-flash", "Google"),
    ("mistral/mistral-large-latest", "Mistral"),
]

_DEFAULT_JUDGE_PROMPT = (
    "Review each phase for: code correctness, adherence to requirements, "
    "edge-case handling, security issues, and consistency with the project style."
)


def _provider_for_model(model: str) -> str:
    """Infer provider name from a model string."""
    if model.startswith("chatgpt/"):
        return "chatgpt"
    if model.startswith("gemini/"):
        return "google"
    if model.startswith("mistral/"):
        return "mistral"
    if "claude" in model.lower():
        return "anthropic"
    if "gpt" in model.lower() or "o1" in model.lower() or "o3" in model.lower():
        return "openai"
    return "unknown"


def _write_dotenv_key(key: str, value: str, env_path: Path) -> None:
    """Write or update a single key in a .env file."""
    lines: list[str] = []
    found = False

    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _, _ = stripped.partition("=")
                if k.strip() == key:
                    lines.append(f"{key}={value}")
                    found = True
                    continue
            lines.append(line)

    if not found:
        lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _save_judge_api_key(api_key: str) -> bool:
    """Save API key to system keyring. Returns False on failure."""
    try:
        import keyring

        keyring.set_password("sago", "judge_api_key", api_key)
        return True
    except Exception:
        return False


def _do_judge() -> None:
    console.print(
        Panel(
            "Configure a separate LLM to review generated code\nafter each phase.",
            title="sago judge",
            border_style="blue",
        )
    )

    # --- Model selection ---
    console.print("\n[bold]Select a judge model:[/bold]\n")
    for i, (model, provider) in enumerate(_JUDGE_MODELS, 1):
        console.print(f"  {i}. {model} ({provider})")
    console.print(f"  {len(_JUDGE_MODELS) + 1}. Custom (enter model string)")

    choice = typer.prompt(
        "\nChoice",
        default="1",
    )

    try:
        idx = int(choice) - 1
    except ValueError:
        console.print("[red]Invalid choice[/red]")
        raise typer.Exit(1) from None

    if idx == len(_JUDGE_MODELS):
        model = typer.prompt("Enter model string")
        provider = _provider_for_model(model)
    elif 0 <= idx < len(_JUDGE_MODELS):
        model, provider = _JUDGE_MODELS[idx]
    else:
        console.print("[red]Invalid choice[/red]")
        raise typer.Exit(1)

    console.print(f"\n  Model: [cyan]{model}[/cyan]")
    console.print(f"  Provider: [cyan]{provider.lower()}[/cyan]")

    # --- API key ---
    api_key = typer.prompt(f"\nEnter API key for {provider.lower()}", hide_input=True)

    env_path = Path.cwd() / ".env"
    _write_dotenv_key("JUDGE_MODEL", model, env_path)
    console.print("\n  Saved JUDGE_MODEL to .env")

    if _save_judge_api_key(api_key):
        console.print("  Saved API key to system keyring")
        key_location = "stored in keyring"
    else:
        _write_dotenv_key("JUDGE_API_KEY", api_key, env_path)
        console.print("  [yellow]Keyring unavailable — saved JUDGE_API_KEY to .env[/yellow]")
        key_location = "stored in .env"

    # --- Review prompt ---
    console.print("\n[bold]Review prompt[/bold]")
    console.print(f"  Default: {_DEFAULT_JUDGE_PROMPT[:80]}...")

    custom_prompt = typer.prompt(
        "\nCustom review prompt (or Enter for default)",
        default="",
    )
    prompt = custom_prompt if custom_prompt else _DEFAULT_JUDGE_PROMPT
    prompt_label = "custom" if custom_prompt else "default"
    _write_dotenv_key("JUDGE_PROMPT", prompt, env_path)
    console.print(f"\n  Saved {'custom' if custom_prompt else 'default'} JUDGE_PROMPT to .env")

    # --- Summary ---
    console.print(
        Panel(
            f"Judge configured successfully!\n\n"
            f"  Model:  {model}\n"
            f"  Key:    {key_location}\n"
            f"  Prompt: {prompt_label}\n\n"
            f"The judge will automatically review code after each\n"
            f"phase during execution by your coding agent.",
            title="Configuration Complete",
            border_style="green",
        )
    )


@app.command()
def judge() -> None:
    """Configure the judge LLM for post-phase code reviews."""
    try:
        _do_judge()
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def _do_lint_plan(project_path: Path, strict: bool, json_output: bool) -> None:
    """Validate PLAN.md and display results."""
    parser = MarkdownParser()
    plan_file = project_path / "PLAN.md"

    if not plan_file.exists():
        console.print("[red]No PLAN.md found.[/red]")
        console.print("[yellow]Run `sago plan` first[/yellow]")
        raise typer.Exit(1)

    content = plan_file.read_text(encoding="utf-8")

    try:
        phases = parser.parse_xml_tasks(content)
    except ValueError as e:
        console.print(f"[red]Failed to parse PLAN.md: {e}[/red]")
        raise typer.Exit(1) from None

    from sago.models.plan import Plan
    from sago.validation import PlanValidator

    plan = Plan(phases=phases)
    validator = PlanValidator()
    result = validator.validate(plan)

    if json_output:
        console.print(result.model_dump_json(indent=2))
        raise typer.Exit(0 if result.valid else 1)

    if not result.issues:
        console.print("[green]Plan is valid. No issues found.[/green]")
        raise typer.Exit(0)

    style_map = {"error": "red", "warning": "yellow", "suggestion": "blue"}

    for issue in result.issues:
        style = style_map.get(issue.severity, "dim")
        label = issue.severity.upper()
        loc = ""
        if issue.task_id:
            loc = f" (task {issue.task_id})"
        elif issue.phase_name:
            loc = f" ({issue.phase_name})"
        console.print(f"  [{style}]{label}[/{style}]{loc}: {issue.message}")

    error_count = len(result.errors)
    warn_count = len(result.warnings)
    sug_count = len(result.suggestions)
    console.print(f"\n  {error_count} error(s), {warn_count} warning(s), {sug_count} suggestion(s)")

    if not result.valid:
        raise typer.Exit(1)

    if strict and warn_count > 0:
        console.print("[yellow]Strict mode: warnings treated as errors[/yellow]")
        raise typer.Exit(1)

    raise typer.Exit(0)


@app.command(name="lint-plan")
def lint_plan(
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
    strict: bool = typer.Option(False, "--strict", help="Treat warnings as errors"),
    json_output: bool = typer.Option(False, "--json", help="Output JSON for CI integration"),
) -> None:
    """Validate PLAN.md for structural and semantic issues."""
    try:
        _do_lint_plan(project_path, strict, json_output)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def _do_next(project_path: Path) -> None:
    _load_config(project_path)
    manager = ProjectManager(config)
    parser = MarkdownParser()

    if not manager.is_sago_project(project_path):
        console.print(f"[red]Not a sago project: {project_path}[/red]")
        raise typer.Exit(1)

    plan_file = project_path / "PLAN.md"
    if not plan_file.exists():
        console.print("[red]No PLAN.md found.[/red]")
        console.print("[yellow]Run `sago plan` first[/yellow]")
        raise typer.Exit(1)

    phases = parser.parse_xml_tasks(plan_file.read_text(encoding="utf-8"))
    state_mgr = StateManager(project_path / "STATE.md")
    task_states = state_mgr.get_task_states(phases)

    # Build lookup of task status by ID
    status_by_id = {ts.task_id: ts.status for ts in task_states}

    # Find the next task: first PENDING task whose dependencies are all DONE
    for phase in phases:
        for task in phase.tasks:
            if status_by_id.get(task.id) != TaskStatus.PENDING:
                continue

            # Check dependencies
            if task.depends_on:
                deps_met = all(status_by_id.get(dep) == TaskStatus.DONE for dep in task.depends_on)
            else:
                # No explicit depends_on: depends on all prior tasks in phase
                prior_before = []
                for t in phase.tasks:
                    if t.id == task.id:
                        break
                    prior_before.append(t.id)
                deps_met = all(status_by_id.get(pid) == TaskStatus.DONE for pid in prior_before)

            if not deps_met:
                continue

            # Found the next task
            console.print(Panel(f"[bold]{task.id}: {task.name}[/bold]", title="Next Task"))

            info_table = Table(show_header=False, padding=(0, 2))
            info_table.add_row("[cyan]Phase[/cyan]", phase.name)
            info_table.add_row("[cyan]Files[/cyan]", "\n".join(task.files) if task.files else "—")
            info_table.add_row("[cyan]Verify[/cyan]", task.verify or "—")
            info_table.add_row("[cyan]Done[/cyan]", task.done or "—")
            console.print(info_table)

            # Warn about dangerous verify commands
            if task.verify:
                from sago.validation import check_verify_safety

                safety_warnings = check_verify_safety(task.verify)
                for warning in safety_warnings:
                    console.print(f"  [red]⚠ SAFETY:[/red] [yellow]{warning}[/yellow]")

            if task.depends_on:
                dep_parts = []
                for dep_id in task.depends_on:
                    dep_status = status_by_id.get(dep_id, TaskStatus.PENDING)
                    dep_parts.append(f"{dep_id} ({dep_status.value})")
                console.print(f"\n  [dim]Depends on: {', '.join(dep_parts)}[/dim]")

            console.print(f"\n[bold]Action:[/bold]\n{task.action}")

            # Show resume context if available
            rp = state_mgr.get_resume_point()
            if rp and rp.failure_reason != "None":
                console.print(f"\n[yellow]Previous failure:[/yellow] {rp.failure_reason}")

            return

    # No pending tasks found
    all_done = all(ts.status == TaskStatus.DONE for ts in task_states)
    if all_done:
        console.print("[green]All tasks complete![/green]")
    else:
        failed = [ts for ts in task_states if ts.status == TaskStatus.FAILED]
        console.print("[yellow]No actionable tasks found.[/yellow]")
        if failed:
            console.print(f"  {len(failed)} task(s) failed — run `sago replan` to adjust the plan.")


@app.command(name="next")
def next_task(
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
) -> None:
    """Show the next task to work on.

    Reads PLAN.md and STATE.md, finds the first pending task whose dependencies
    are satisfied, and displays its full details including action and context.
    """
    try:
        _do_next(project_path)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def _do_checkpoint(
    project_path: Path,
    task_id: str,
    status: str,
    notes: str,
    next_task: str,
    next_action: str,
    decisions: list[str],
    phase: str,
    git_tag: bool,
) -> None:
    manager = ProjectManager(config)
    if not manager.is_sago_project(project_path):
        console.print(f"[red]Not a sago project: {project_path}[/red]")
        raise typer.Exit(1)

    plan_file = project_path / "PLAN.md"
    if not plan_file.exists():
        console.print("[red]No PLAN.md found.[/red]")
        raise typer.Exit(1)

    # Resolve task name and phase from plan
    parser = MarkdownParser()
    phases = parser.parse_xml_tasks(plan_file.read_text(encoding="utf-8"))
    task_name = ""
    phase_name = phase
    phase_task_ids: list[str] = []
    for p in phases:
        for t in p.tasks:
            if t.id == task_id:
                task_name = t.name
                if not phase_name:
                    phase_name = p.name
                phase_task_ids = [pt.id for pt in p.tasks]
                break

    if not task_name:
        console.print(f"[red]Task {task_id} not found in PLAN.md[/red]")
        raise typer.Exit(1)

    task_status = TaskStatus(status)

    state_mgr = StateManager(project_path / "STATE.md")
    cp_result = state_mgr.checkpoint(
        task_id=task_id,
        task_name=task_name,
        status=task_status,
        notes=notes,
        phase_name=phase_name,
        next_task=next_task,
        next_action=next_action,
        decisions=decisions if decisions else None,
        phase_task_ids=phase_task_ids,
    )

    icon = {"done": "✓", "failed": "✗", "skipped": "⊘"}[status]
    console.print(f"[green][{icon}] {task_id}: {task_name}[/green]")

    if notes:
        console.print(f"  [dim]{notes}[/dim]")

    if decisions:
        console.print("  [cyan]Decisions:[/cyan]")
        for d in decisions:
            console.print(f"    • {d}")

    if next_task:
        console.print(f"  [yellow]Next → {next_task}[/yellow]")

    if cp_result.phase_completed:
        console.print(f"\n  [green bold]Phase complete: {cp_result.phase_name}[/green bold]")
        console.print("  [yellow]Run `sago replan` before starting the next phase.[/yellow]")

    # Create git tag for successful tasks
    if git_tag and task_status == TaskStatus.DONE:
        import subprocess

        tag_name = f"sago-checkpoint-{task_id}"
        try:
            subprocess.run(
                ["git", "tag", tag_name],
                cwd=project_path,
                capture_output=True,
                check=True,
            )
            console.print(f"  [dim]Tagged: {tag_name}[/dim]")
        except subprocess.CalledProcessError:
            console.print(f"  [yellow]Tag {tag_name} already exists or git not available[/yellow]")


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
        console.print(f"[red]Invalid status: {status}. Must be done, failed, or skipped.[/red]")
        raise typer.Exit(1)
    try:
        _do_checkpoint(
            project_path=project_path,
            task_id=task_id,
            status=status,
            notes=notes,
            next_task=next_task,
            next_action=next_action,
            decisions=decisions,
            phase=phase,
            git_tag=git_tag,
        )
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


@app.command()
def version() -> None:
    """Show sago version."""
    from sago import __version__

    console.print(f"[bold]sago[/bold] version {__version__}")


if __name__ == "__main__":
    app()
