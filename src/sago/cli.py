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
        config = Config(_env_file=env_file)
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


def _get_completed_task_ids(state_file: Path) -> list[str]:
    """Parse completed task IDs from STATE.md."""
    if not state_file.exists():
        return []
    import re

    content = state_file.read_text(encoding="utf-8")
    return re.findall(r"\[(?:✓|✗)\]\s+(\d+\.\d+):", content)


def _show_task_progress(phases: list, completed_tasks: list[str], detailed: bool) -> None:
    """Display task progress summary and optional per-phase breakdown."""
    completed_set = set(completed_tasks)
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
            style = "[green]" if task.id in completed_set else "[dim]"
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
        console.print(
            Panel(dep_text, title="Dependencies", border_style="blue")
        )

    return dependencies


def _do_status(project_path: Path, detailed: bool) -> None:
    _load_config(project_path)
    manager = ProjectManager(config)
    parser = MarkdownParser()

    if not manager.is_sago_project(project_path):
        console.print(f"[red]Not a sago project: {project_path}[/red]")
        raise typer.Exit(1)

    info = manager.get_project_info(project_path)

    state_file = project_path / "STATE.md"
    state = (
        parser.parse_state_file(state_file)
        if state_file.exists()
        else {"active_phase": "Unknown", "current_task": "Unknown"}
    )

    console.print(Panel(f"[bold]{info['name']}[/bold]", title="Project Status"))

    table = Table(show_header=False)
    table.add_row("[cyan]Active Phase[/cyan]", state.get("active_phase", "Unknown"))
    table.add_row("[cyan]Current Task[/cyan]", state.get("current_task", "Unknown"))
    table.add_row("[cyan]Path[/cyan]", str(info["path"]))
    console.print(table)

    plan_file = project_path / "PLAN.md"
    if plan_file.exists():
        try:
            phases = parser.parse_xml_tasks(plan_file.read_text(encoding="utf-8"))
            if phases:
                completed_tasks = _get_completed_task_ids(state_file)
                _show_task_progress(phases, completed_tasks, detailed)
        except Exception as e:
            console.print(f"\n[yellow]Could not parse PLAN.md: {e}[/yellow]")

    if state.get("blockers"):
        console.print("\n[yellow]Known Blockers:[/yellow]")
        for blocker in state["blockers"]:
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


def _do_plan(project_path: Path, force: bool) -> None:
    _load_config(project_path)
    _check_llm_configured()

    manager = ProjectManager(config)

    if not manager.is_sago_project(project_path):
        console.print(f"[red]Not a sago project: {project_path}[/red]")
        console.print("[yellow]Run 'sago init' first[/yellow]")
        raise typer.Exit(1)

    plan_file = project_path / "PLAN.md"
    if plan_file.exists() and not force:
        console.print("[yellow]PLAN.md already exists[/yellow]")
        if not typer.confirm("Overwrite?"):
            raise typer.Exit(0)

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
) -> None:
    """Generate PLAN.md from requirements and project context."""
    try:
        _do_plan(project_path, force)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


def _get_phase_status(
    phases: list, task_states: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """Group task states by phase, returning per-phase status.

    Returns list of dicts: {name, done, failed, pending, total, status}
    where status is 'complete', 'partial', or 'pending'.
    """
    state_by_id = {ts["id"]: ts["status"] for ts in task_states}
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
        result.append({
            "name": phase.name,
            "done": done,
            "failed": failed,
            "pending": pending,
            "total": len(phase.tasks),
            "status": status,
        })
    return result


def _write_phase_summary_to_state(
    state_file: Path, phase_name: str, review_output: str
) -> None:
    """Append a phase summary to STATE.md (skips if already present)."""
    header = f"## Phase Summary: {phase_name}"
    existing = state_file.read_text(encoding="utf-8") if state_file.exists() else ""
    if header in existing:
        return
    block = f"\n{header}\n\n{review_output}\n"
    state_file.write_text(existing + block, encoding="utf-8")


def _show_plan_diff(
    old_phases: list, new_phases: list
) -> None:
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
        if (old_t.name != new_t.name or old_t.action != new_t.action
                or old_t.files != new_t.files or old_t.verify != new_t.verify):
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


def _do_replan(project_path: Path) -> None:
    _load_config(project_path)
    _check_llm_configured()

    manager = ProjectManager(config)
    parser = MarkdownParser()

    if not manager.is_sago_project(project_path):
        console.print(f"[red]Not a sago project: {project_path}[/red]")
        console.print("[yellow]Run 'sago init' first[/yellow]")
        raise typer.Exit(1)

    plan_file = project_path / "PLAN.md"
    if not plan_file.exists():
        console.print("[red]No PLAN.md found.[/red]")
        console.print("[yellow]Run `sago plan` first[/yellow]")
        raise typer.Exit(1)

    plan_content = plan_file.read_text(encoding="utf-8")
    old_phases = parser.parse_xml_tasks(plan_content)

    # Parse STATE.md for current status
    state_file = project_path / "STATE.md"
    task_states: list[dict[str, str]] = []
    if state_file.exists():
        state_content = state_file.read_text(encoding="utf-8")
        task_states = parser.parse_state_tasks(state_content, old_phases)
    else:
        for phase in old_phases:
            for task in phase.tasks:
                task_states.append({
                    "id": task.id, "name": task.name,
                    "status": "pending", "phase_name": phase.name,
                })

    done_count = sum(1 for ts in task_states if ts["status"] == "done")
    failed_count = sum(1 for ts in task_states if ts["status"] == "failed")
    pending_count = sum(1 for ts in task_states if ts["status"] == "pending")
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
            review_result = asyncio.run(
                orchestrator.run_review(project_path, phase, review_prompt)
            )

        if review_result.success:
            review_text = review_result.output
            review_outputs.append(review_text)
            console.print(
                Panel(review_text, title=f"Review: {ps['name']}", border_style="cyan")
            )
            _write_phase_summary_to_state(state_file, ps["name"], review_text)
        else:
            console.print(
                f"[yellow]Review failed for {ps['name']}: {review_result.error}[/yellow]"
            )

    # Prompt for feedback
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

    # Parse new plan and show diff
    new_content = plan_file.read_text(encoding="utf-8")
    new_phases = parser.parse_xml_tasks(new_content)

    _show_plan_diff(old_phases, new_phases)

    if not typer.confirm("\nApply changes?"):
        plan_file.write_text(old_plan_backup, encoding="utf-8")
        console.print("[dim]Changes reverted.[/dim]")
        raise typer.Exit(0)

    console.print("\n[green]Plan updated successfully![/green]")
    _show_plan_summary(project_path)


@app.command()
def replan(
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
) -> None:
    """Update PLAN.md based on your feedback without regenerating from scratch."""
    try:
        _do_replan(project_path)
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


@app.command()
def version() -> None:
    """Show sago version."""
    from sago import __version__

    console.print(f"[bold]sago[/bold] version {__version__}")


if __name__ == "__main__":
    app()
