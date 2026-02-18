import asyncio
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from sago.agents.orchestrator import Orchestrator
from sago.blocker.manager import HostsManager
from sago.core.config import Config
from sago.core.parser import MarkdownParser
from sago.core.project import ProjectManager
from sago.utils.cost_estimator import CostEstimator
from sago.utils.elevation import check_elevation_available, is_admin

app = typer.Typer(
    name="sago",
    help="sago - AI-powered project orchestration CLI",
    add_completion=False,
)

console = Console()
config = Config()


def _do_init(
    project_name: str | None, path: Path | None, interactive: bool, overwrite: bool
) -> None:
    if interactive:
        console.print("[bold blue]sago Project Initialization[/bold blue]\n")
        project_name = typer.prompt("Project name", default=project_name or "my-project")

    if not project_name:
        console.print("[red]Project name is required[/red]")
        raise typer.Exit(1)

    project_path = path or Path.cwd() / project_name
    manager = ProjectManager(config)
    manager.init_project(project_path, project_name=project_name, overwrite=overwrite)

    console.print(f"\n[green]Project initialized at: {project_path}[/green]")
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. cd " + str(project_path))
    console.print("  2. Edit PROJECT.md and REQUIREMENTS.md")
    console.print("  3. Run: sago plan")
    console.print("  4. Run: sago execute")


@app.command()
def init(
    project_name: str | None = typer.Argument(None, help="Project name"),
    path: Path | None = typer.Option(None, "--path", "-p", help="Project path"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Interactive mode"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing files"),
) -> None:
    try:
        _do_init(project_name, path, interactive, overwrite)
    except FileExistsError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


def _get_completed_task_ids(state_file: Path) -> list[str]:
    """Parse completed task IDs from STATE.md."""
    if not state_file.exists():
        return []
    import re

    content = state_file.read_text(encoding="utf-8")
    return re.findall(r"\[(?:✓|✗)\]\s+(\d+\.\d+):", content)


def _show_task_progress(
    phases: list, completed_tasks: list[str], detailed: bool
) -> None:
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


def _do_status(project_path: Path, detailed: bool) -> None:
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
        console.print("\n[bold]Available Commands:[/bold]")
        console.print("   sago execute     - Execute tasks from plan")
        console.print("   sago run         - Complete workflow (plan + execute)")
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
        raise typer.Exit(1)


def _do_block(domains: list[str], hosts_file: Path | None) -> None:
    manager = HostsManager(hosts_file)

    _, method = check_elevation_available()
    if not is_admin():
        console.print(
            f"[yellow]This command requires elevation ({method})[/yellow]"
        )
        if not typer.confirm("Continue?"):
            raise typer.Exit(0)

    manager.block_sites(domains)

    console.print(f"[green]Blocked {len(domains)} domain(s)[/green]")
    for domain in domains:
        console.print(f"  - {domain}")


@app.command()
def block(
    domains: list[str] = typer.Argument(..., help="Domains to block"),
    hosts_file: Path | None = typer.Option(None, help="Custom hosts file path"),
) -> None:
    """Block websites via hosts file."""
    try:
        _do_block(domains, hosts_file)
    except PermissionError as e:
        console.print(f"[red]{e}[/red]")
        console.print("[yellow]Try running with sudo (Unix) or as Administrator (Windows)[/yellow]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def unblock(
    domains: list[str] | None = typer.Argument(
        None, help="Domains to unblock (all if not specified)"
    ),
    hosts_file: Path | None = typer.Option(None, help="Custom hosts file path"),
) -> None:
    """Unblock websites."""
    try:
        manager = HostsManager(hosts_file)

        if not is_admin():
            console.print("[yellow]This command requires elevation[/yellow]")
            if not typer.confirm("Continue?"):
                raise typer.Exit(0)

        manager.unblock_sites(domains)

        if domains:
            console.print(f"[green]Unblocked {len(domains)} domain(s)[/green]")
        else:
            console.print("[green]Unblocked all domains[/green]")

    except PermissionError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command(name="block-list")
def block_list(
    hosts_file: Path | None = typer.Option(None, help="Custom hosts file path"),
) -> None:
    """Show currently blocked domains."""
    try:
        manager = HostsManager(hosts_file)
        blocked = manager.get_blocked_domains()

        if not blocked:
            console.print("[yellow]No domains are currently blocked[/yellow]")
            return

        console.print(f"[bold]Blocked Domains ({len(blocked)}):[/bold]\n")
        for domain in blocked:
            console.print(f"  - {domain}")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


def _do_plan(project_path: Path, force: bool) -> None:
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

    orchestrator = Orchestrator(config=config)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(description="Generating plan...", total=None)
        result = asyncio.run(
            orchestrator.run_workflow(
                project_path=project_path, plan=True, execute=False,
            )
        )

    if result.success:
        console.print("\n[green]Plan generated successfully![/green]")
        console.print(f"   {plan_file}")

        if result.task_executions:
            metadata = result.task_executions[0].execution_result.metadata
            console.print("\n[bold]Summary:[/bold]")
            console.print(f"   Phases: {metadata.get('num_phases', 0)}")
            console.print(f"   Tasks: {metadata.get('num_tasks', 0)}")

        console.print("\n[bold]Next steps:[/bold]")
        console.print("   1. Review PLAN.md")
        console.print("   2. Run: sago execute")
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
        raise typer.Exit(1)


def _do_execute(
    project_path: Path, verify: bool, max_retries: int,
    continue_on_failure: bool, compress: bool,
) -> None:
    manager = ProjectManager(config)

    if not manager.is_sago_project(project_path):
        console.print(f"[red]Not a sago project: {project_path}[/red]")
        raise typer.Exit(1)

    plan_file = project_path / "PLAN.md"
    if not plan_file.exists():
        console.print("[red]PLAN.md not found[/red]")
        console.print("[yellow]Run 'sago plan' first[/yellow]")
        raise typer.Exit(1)

    run_config = config
    if compress:
        run_config = config.model_copy(update={"enable_compression": True})

    orchestrator = Orchestrator(config=run_config)
    console.print("[bold blue]Executing tasks...[/bold blue]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(description="Running workflow...", total=None)
        result = asyncio.run(
            orchestrator.run_workflow(
                project_path=project_path, plan=False, execute=True,
                verify=verify, max_retries=max_retries,
                continue_on_failure=continue_on_failure,
            )
        )
        progress.update(task, completed=True)

    console.print("\n[bold]Execution Complete![/bold]\n")
    _show_workflow_result(result)

    if result.task_executions:
        for task_exec in result.task_executions:
            if task_exec.retry_count > 0:
                console.print(
                    f"     [yellow]Retries for {task_exec.task.id}: "
                    f"{task_exec.retry_count}[/yellow]"
                )
            if not task_exec.success:
                error = task_exec.execution_result.error or "Unknown error"
                console.print(f"     [red]Error: {error}[/red]")

    if result.success:
        console.print("\n[green]All tasks completed successfully![/green]")
        console.print("\n[bold]Next steps:[/bold]")
        console.print("   1. Review generated code")
        console.print("   2. Run tests: pytest")
        console.print("   3. Check STATE.md for progress log")
    else:
        console.print("\n[yellow]Some tasks failed[/yellow]")
        console.print("\n[bold]Troubleshooting:[/bold]")
        console.print("   1. Check STATE.md for error details")
        console.print("   2. Fix issues manually")
        console.print("   3. Re-run: sago execute")

    raise typer.Exit(0 if result.success else 1)


@app.command()
def execute(
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
    verify: bool = typer.Option(True, "--verify/--no-verify", help="Run verification commands"),
    max_retries: int = typer.Option(2, "--max-retries", help="Maximum retries per task"),
    continue_on_failure: bool = typer.Option(
        False, "--continue-on-failure", help="Continue if a task fails"
    ),
    compress: bool = typer.Option(False, "--compress", help="Enable context compression"),
) -> None:
    """Execute tasks from PLAN.md."""
    try:
        _do_execute(project_path, verify, max_retries, continue_on_failure, compress)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


def _show_workflow_result(result: Any) -> None:
    table = Table(show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green" if result.success else "red")

    table.add_row("Status", "SUCCESS" if result.success else "FAILED")
    table.add_row("Total Tasks", str(result.total_tasks))
    table.add_row("Completed", str(result.completed_tasks))
    table.add_row("Failed", str(result.failed_tasks))
    table.add_row("Duration", f"{result.total_duration:.1f}s")
    console.print(table)

    if result.task_executions:
        console.print("\n[bold]Task Summary:[/bold]")
        for task_exec in result.task_executions:
            mark = "[green]ok[/green]" if task_exec.success else "[red]FAIL[/red]"
            console.print(f"  {mark} {task_exec.task.id}: {task_exec.task.name}")


def _validate_project(project_path: Path) -> None:
    """Validate project exists and has required files. Exits on failure."""
    manager = ProjectManager(config)
    if not manager.is_sago_project(project_path):
        console.print(f"[red]Not a sago project: {project_path}[/red]")
        raise typer.Exit(1)

    required_files = ["PROJECT.md", "REQUIREMENTS.md"]
    missing = [f for f in required_files if not (project_path / f).exists()]
    if missing:
        console.print(f"[red]Missing required files: {', '.join(missing)}[/red]")
        raise typer.Exit(1)


def _run_dry_run(
    project_path: Path, generate_plan: bool, verify: bool
) -> None:
    """Show cost estimate and prompt for confirmation. Exits if cancelled."""
    console.print("\n[bold cyan]Cost Estimation Mode[/bold cyan]\n")

    plan_file = project_path / "PLAN.md"
    if not plan_file.exists():
        console.print("[red]PLAN.md not found. Run without --dry-run first.[/red]")
        raise typer.Exit(1)

    parser = MarkdownParser()
    phases = parser.parse_xml_tasks(plan_file.read_text(encoding="utf-8"))
    all_tasks = [task for phase in phases for task in phase.tasks]

    estimator = CostEstimator(model=config.llm_model)
    estimate = estimator.estimate_workflow(
        all_tasks, generate_plan=generate_plan, verify=verify
    )
    console.print(estimate)

    console.print("\n[bold]Proceed with execution?[/bold]")
    if not typer.confirm("Continue"):
        console.print("[yellow]Cancelled[/yellow]")
        raise typer.Exit(0)


def _print_enabled_flags(
    use_cache: bool, git_commit: bool, auto_retry: bool, focus: bool, compress: bool
) -> None:
    """Print which optional flags are enabled."""
    for flag, label in [
        (use_cache, "Smart caching"),
        (git_commit, "Git auto-commit"),
        (auto_retry, "Auto-retry"),
        (focus, "Focus mode"),
        (compress, "Context compression"),
    ]:
        if flag:
            console.print(f"[dim]{label} enabled[/dim]")


def _do_run(
    project_path: Path, verify: bool, max_retries: int,
    continue_on_failure: bool, force_plan: bool, dry_run: bool,
    use_cache: bool, git_commit: bool, auto_retry: bool,
    focus: bool, compress: bool,
) -> None:
    _validate_project(project_path)

    plan_file = project_path / "PLAN.md"
    if plan_file.exists() and not force_plan:
        console.print("[yellow]PLAN.md already exists[/yellow]")
        generate_plan = typer.confirm("Regenerate plan?")
    else:
        generate_plan = True

    if dry_run:
        _run_dry_run(project_path, generate_plan, verify)

    run_config = config
    if compress:
        run_config = config.model_copy(update={"enable_compression": True})

    _print_enabled_flags(use_cache, git_commit, auto_retry, focus, compress)

    orchestrator = Orchestrator(config=run_config)
    console.print("[bold blue]Running complete workflow...[/bold blue]\n")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(description="Executing workflow...", total=None)
        result = asyncio.run(
            orchestrator.run_workflow(
                project_path=project_path, plan=generate_plan,
                execute=True, verify=verify, max_retries=max_retries,
                continue_on_failure=continue_on_failure,
                git_commit=git_commit, self_heal=auto_retry,
                focus_mode=focus, use_cache=use_cache,
            )
        )
        progress.update(task, completed=True)

    console.print("\n[bold]Workflow Complete![/bold]\n")
    _show_workflow_result(result)

    if result.success:
        console.print("\n[green]Workflow completed successfully![/green]")
    else:
        console.print("\n[yellow]Workflow completed with errors[/yellow]")
        console.print("   Check STATE.md for details")

    raise typer.Exit(0 if result.success else 1)


@app.command()
def run(
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
    verify: bool = typer.Option(True, "--verify/--no-verify", help="Run verification commands"),
    max_retries: int = typer.Option(2, "--max-retries", help="Maximum retries per task"),
    continue_on_failure: bool = typer.Option(
        False, "--continue-on-failure", help="Continue if a task fails"
    ),
    force_plan: bool = typer.Option(False, "--force-plan", help="Regenerate PLAN.md if exists"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Estimate cost without executing"),
    use_cache: bool = typer.Option(True, "--cache/--no-cache", help="Use smart caching"),
    git_commit: bool = typer.Option(False, "--git-commit", help="Auto-commit after each task"),
    auto_retry: bool = typer.Option(False, "--auto-retry", help="Auto-fix failed tasks"),
    focus: bool = typer.Option(False, "--focus", help="Block distracting sites during workflow"),
    compress: bool = typer.Option(False, "--compress", help="Enable context compression"),
) -> None:
    try:
        _do_run(
            project_path, verify, max_retries, continue_on_failure,
            force_plan, dry_run, use_cache, git_commit, auto_retry, focus, compress,
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show sago version."""
    from sago import __version__

    console.print(f"[bold]sago[/bold] version {__version__}")


if __name__ == "__main__":
    app()
