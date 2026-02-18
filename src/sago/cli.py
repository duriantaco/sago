import asyncio
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from sago.agents.orchestrator import Orchestrator
from sago.core.config import Config
from sago.core.parser import MarkdownParser
from sago.core.project import ProjectManager
from sago.utils.cost_estimator import CostEstimator

app = typer.Typer(
    name="sago",
    help="sago - AI-powered project orchestration CLI",
    add_completion=False,
)

console = Console()
config = Config()


def _do_init(
    project_name: str | None,
    path: Path | None,
    interactive: bool,
    overwrite: bool,
    prompt: str | None = None,
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

    if prompt:
        console.print("[dim]Generating project files from prompt...[/dim]")
        try:
            asyncio.run(manager.generate_from_prompt(prompt, project_path, project_name))
            console.print("[green]Generated PROJECT.md and REQUIREMENTS.md from prompt[/green]")
        except Exception as e:
            console.print(f"[yellow]LLM generation failed: {e}[/yellow]")
            console.print("[dim]Template files are still available — edit them manually[/dim]")

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
    prompt: str | None = typer.Option(
        None, "--prompt", help="Generate project files from a one-line description"
    ),
) -> None:
    if prompt and interactive:
        console.print("[red]--prompt and --interactive are mutually exclusive[/red]")
        raise typer.Exit(1)
    try:
        _do_init(project_name, path, interactive, overwrite, prompt=prompt)
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
    continue_on_failure: bool, compress: bool, trace: bool = False,
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

    updates: dict[str, object] = {}
    if compress:
        updates["enable_compression"] = True
    if trace:
        updates["enable_tracing"] = True
    run_config = config.model_copy(update=updates) if updates else config

    dashboard_server = None
    if trace:
        from sago.web.server import start_dashboard

        trace_path = project_path / ".planning" / "trace.jsonl"
        dashboard_server = start_dashboard(trace_path, open_browser=True)
        console.print(
            f"[dim]Dashboard: http://127.0.0.1:{dashboard_server.server_address[1]}[/dim]"
        )

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
    trace: bool = typer.Option(False, "--trace", help="Enable tracing + open dashboard"),
) -> None:
    """Execute tasks from PLAN.md."""
    try:
        _do_execute(project_path, verify, max_retries, continue_on_failure, compress, trace)
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
    use_cache: bool, git_commit: bool, auto_retry: bool,
    compress: bool, trace: bool = False,
) -> None:
    """Print which optional flags are enabled."""
    for flag, label in [
        (use_cache, "Smart caching"),
        (git_commit, "Git auto-commit"),
        (auto_retry, "Auto-retry"),
        (compress, "Context compression"),
        (trace, "Tracing dashboard"),
    ]:
        if flag:
            console.print(f"[dim]{label} enabled[/dim]")


def _do_run(
    project_path: Path, verify: bool, max_retries: int,
    continue_on_failure: bool, force_plan: bool, dry_run: bool,
    use_cache: bool, git_commit: bool, auto_retry: bool,
    compress: bool, trace: bool = False,
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

    updates: dict[str, object] = {}
    if compress:
        updates["enable_compression"] = True
    if trace:
        updates["enable_tracing"] = True
    run_config = config.model_copy(update=updates) if updates else config

    _print_enabled_flags(use_cache, git_commit, auto_retry, compress, trace)

    dashboard_server = None
    if trace:
        from sago.web.server import start_dashboard

        trace_path = project_path / ".planning" / "trace.jsonl"
        dashboard_server = start_dashboard(trace_path, open_browser=True)
        console.print(
            f"[dim]Dashboard: http://127.0.0.1:{dashboard_server.server_address[1]}[/dim]"
        )

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
                use_cache=use_cache,
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
    compress: bool = typer.Option(False, "--compress", help="Enable context compression"),
    trace: bool = typer.Option(False, "--trace", help="Enable tracing + open dashboard"),
) -> None:
    try:
        _do_run(
            project_path, verify, max_retries, continue_on_failure,
            force_plan, dry_run, use_cache, git_commit, auto_retry, compress, trace,
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@app.command(name="trace")
def trace_cmd(
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
    port: int = typer.Option(0, "--port", help="Server port (0=auto)"),
    trace_file: Path | None = typer.Option(None, "--file", "-f", help="Trace JSONL file"),
    demo: bool = typer.Option(False, "--demo", help="Generate sample trace and open dashboard"),
) -> None:
    """Open the observability dashboard for a past trace."""
    from sago.web.server import start_dashboard

    if demo:
        path = _generate_demo_trace()
    else:
        path = trace_file or (project_path / ".planning" / "trace.jsonl")
        if not path.exists():
            console.print(f"[red]Trace file not found: {path}[/red]")
            console.print("[yellow]Run with --trace first, or use --demo for a sample[/yellow]")
            raise typer.Exit(1)

    server = start_dashboard(path, port=port, open_browser=True)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    console.print(f"[green]Dashboard running at {url}[/green]")
    console.print("[dim]Press Ctrl+C to stop[/dim]")

    try:
        import time

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()
        console.print("\n[dim]Dashboard stopped[/dim]")


def _generate_demo_trace() -> Path:
    """Generate a realistic demo trace file with streaming delay."""
    import json
    import tempfile
    import threading
    import uuid
    from datetime import UTC, datetime, timedelta

    trace_id = uuid.uuid4().hex[:12]
    tmp = Path(tempfile.mkdtemp()) / "demo-trace.jsonl"
    base = datetime.now(UTC)

    def ts(offset_s: float) -> str:
        return (base + timedelta(seconds=offset_s)).isoformat()

    def evt(
        t: float, event_type: str, agent: str, data: dict, duration_ms: float | None = None
    ) -> dict:
        return {
            "event_type": event_type,
            "timestamp": ts(t),
            "trace_id": trace_id,
            "span_id": uuid.uuid4().hex[:8],
            "agent": agent,
            "data": data,
            "parent_span_id": None,
            "duration_ms": duration_ms,
        }

    events = [
        # Workflow start
        evt(0, "workflow_start", "Orchestrator", {"project_path": "/home/user/weather-app"}),
        # Planning phase - file reads
        evt(0.5, "file_read", "PlannerAgent", {
            "path": "PROJECT.md",
            "size_bytes": 1247,
            "content_preview": "# Weather Dashboard\n\nA modern weather dashboard built with FastAPI and PostgreSQL.\n\n## Tech Stack\n- Python 3.12\n- FastAPI + Uvicorn\n- PostgreSQL + SQLAlchemy\n- Jinja2 templates\n- OpenWeatherMap API",
        }),
        evt(0.8, "file_read", "PlannerAgent", {
            "path": "REQUIREMENTS.md",
            "size_bytes": 892,
            "content_preview": "# Requirements\n\n* [x] **REQ-1:** Display current weather for user's location\n* [ ] **REQ-2:** Show 5-day forecast with min/max temperatures\n* [ ] **REQ-3:** Allow searching by city name with autocomplete\n* [ ] **REQ-4:** Store search history in PostgreSQL",
        }),
        evt(1.0, "file_read", "PlannerAgent", {
            "path": "STATE.md",
            "size_bytes": 340,
            "content_preview": "# State\n\n## Completed Tasks\nNone yet.\n\n## Current Phase\nPlanning",
        }),
        # Planning LLM call
        evt(1.2, "llm_call", "PlannerAgent", {
            "model": "gpt-4o",
            "prompt_tokens": 2140,
            "completion_tokens": 1860,
            "total_tokens": 4000,
            "duration_s": 6.3,
            "prompt_preview": "Based on the project context below, generate a detailed PLAN.md with atomic tasks.\n\nProject Context:\n=== PROJECT.md ===\n# Weather Dashboard\nA modern weather dashboard built with FastAPI...",
            "response_preview": "<phases>\n  <phase name=\"Phase 1: Foundation\">\n    <task id=\"1.1\">\n      <name>Create project structure and config</name>\n      <files>src/config.py, src/__init__.py, pyproject.toml</files>\n      <action>Set up project with FastAPI, SQLAlchemy, environment config...</action>\n      <verify>python -c \"from src.config import Settings; print('OK')\"</verify>\n      <done>Config module imports and validates settings</done>\n    </task>\n    <task id=\"1.2\">\n      <name>Set up database models</name>...",
        }, duration_ms=6300),
        # Plan file write
        evt(7.6, "file_write", "PlannerAgent", {
            "path": "PLAN.md",
            "size_bytes": 4120,
            "content_preview": "# PLAN.md\n\n```xml\n<phases>\n  <phase name=\"Phase 1: Foundation\">\n    <task id=\"1.1\">\n      <name>Create project structure and config</name>\n      <files>src/config.py, src/__init__.py, pyproject.toml</files>\n      <action>Set up FastAPI project structure with Pydantic settings...</action>\n      <verify>python -c \"from src.config import Settings; print('OK')\"</verify>\n      <done>Config module imports successfully</done>\n    </task>",
        }),
        # Task 1.1
        evt(8.0, "task_start", "Orchestrator", {
            "task_id": "1.1",
            "task_name": "Create project structure and config",
            "phase": "Phase 1: Foundation",
            "files": ["src/config.py", "src/__init__.py", "pyproject.toml"],
        }),
        evt(8.5, "file_read", "ExecutorAgent", {
            "path": "PROJECT.md",
            "size_bytes": 1247,
            "content_preview": "# Weather Dashboard\n\nA modern weather dashboard...",
        }),
        evt(8.7, "file_read", "ExecutorAgent", {
            "path": "REQUIREMENTS.md",
            "size_bytes": 892,
            "content_preview": "# Requirements\n\n* [x] **REQ-1:** Display current weather...",
        }),
        evt(9.0, "llm_call", "ExecutorAgent", {
            "model": "gpt-4o",
            "prompt_tokens": 1850,
            "completion_tokens": 1420,
            "total_tokens": 3270,
            "duration_s": 5.1,
            "prompt_preview": "Generate code to complete this task:\n\n=== TASK ===\nID: 1.1\nName: Create project structure and config\nPhase: Phase 1: Foundation\n\nAction:\nSet up FastAPI project structure with Pydantic settings for API keys, database URL...",
            "response_preview": "=== FILE: src/config.py ===\n```python\nfrom pydantic_settings import BaseSettings\nfrom functools import lru_cache\n\nclass Settings(BaseSettings):\n    app_name: str = \"Weather Dashboard\"\n    database_url: str = \"postgresql://localhost/weather\"\n    openweather_api_key: str\n    debug: bool = False\n\n    class Config:\n        env_file = \".env\"\n\n@lru_cache\ndef get_settings() -> Settings:\n    return Settings()\n```",
        }, duration_ms=5100),
        evt(14.2, "file_write", "ExecutorAgent", {
            "path": "src/config.py",
            "size_bytes": 380,
            "content_preview": "from pydantic_settings import BaseSettings\nfrom functools import lru_cache\n\nclass Settings(BaseSettings):\n    app_name: str = \"Weather Dashboard\"\n    database_url: str = \"postgresql://localhost/weather\"\n    openweather_api_key: str\n    debug: bool = False\n\n    class Config:\n        env_file = \".env\"\n\n@lru_cache\ndef get_settings() -> Settings:\n    return Settings()",
        }),
        evt(14.4, "file_write", "ExecutorAgent", {
            "path": "src/__init__.py",
            "size_bytes": 42,
            "content_preview": "__version__ = \"0.1.0\"",
        }),
        evt(14.6, "file_write", "ExecutorAgent", {
            "path": "pyproject.toml",
            "size_bytes": 610,
            "content_preview": "[project]\nname = \"weather-dashboard\"\nversion = \"0.1.0\"\nrequires-python = \">=3.12\"\ndependencies = [\n    \"fastapi>=0.109\",\n    \"uvicorn[standard]\",\n    \"sqlalchemy>=2.0\",\n    \"pydantic-settings\",\n    \"httpx\",\n    \"jinja2\",\n]",
        }),
        evt(15.0, "verify_run", "VerifierAgent", {
            "command": "python -c \"from src.config import Settings; print('OK')\"",
            "exit_code": 0,
            "success": True,
            "duration_s": 0.8,
            "stdout": "OK\n",
            "stderr": "",
        }),
        evt(15.9, "task_end", "Orchestrator", {
            "task_id": "1.1",
            "task_name": "Create project structure and config",
            "success": True,
            "duration_s": 7.9,
        }),
        # Task 1.2
        evt(16.0, "task_start", "Orchestrator", {
            "task_id": "1.2",
            "task_name": "Set up database models",
            "phase": "Phase 1: Foundation",
            "files": ["src/models.py", "src/database.py"],
        }),
        evt(16.5, "file_read", "ExecutorAgent", {
            "path": "src/config.py",
            "size_bytes": 380,
            "content_preview": "from pydantic_settings import BaseSettings...",
        }),
        evt(17.0, "llm_call", "ExecutorAgent", {
            "model": "gpt-4o",
            "prompt_tokens": 2100,
            "completion_tokens": 1650,
            "total_tokens": 3750,
            "duration_s": 5.8,
            "prompt_preview": "Generate code to complete this task:\n\n=== TASK ===\nID: 1.2\nName: Set up database models\n\nAction:\nCreate SQLAlchemy models for weather data and search history...",
            "response_preview": "=== FILE: src/models.py ===\n```python\nfrom sqlalchemy import Column, Integer, String, Float, DateTime, func\nfrom sqlalchemy.orm import DeclarativeBase\n\nclass Base(DeclarativeBase):\n    pass\n\nclass SearchHistory(Base):\n    __tablename__ = \"search_history\"\n    id = Column(Integer, primary_key=True)\n    city = Column(String(100), nullable=False)\n    country = Column(String(10))\n    searched_at = Column(DateTime, server_default=func.now())\n```",
        }, duration_ms=5800),
        evt(22.9, "file_write", "ExecutorAgent", {
            "path": "src/models.py",
            "size_bytes": 720,
            "content_preview": "from sqlalchemy import Column, Integer, String, Float, DateTime, func\nfrom sqlalchemy.orm import DeclarativeBase\n\nclass Base(DeclarativeBase):\n    pass\n\nclass SearchHistory(Base):\n    __tablename__ = \"search_history\"\n    id = Column(Integer, primary_key=True)\n    city = Column(String(100), nullable=False)\n    country = Column(String(10))\n    searched_at = Column(DateTime, server_default=func.now())",
        }),
        evt(23.1, "file_write", "ExecutorAgent", {
            "path": "src/database.py",
            "size_bytes": 510,
            "content_preview": "from sqlalchemy import create_engine\nfrom sqlalchemy.orm import sessionmaker\nfrom src.config import get_settings\nfrom src.models import Base\n\nengine = create_engine(get_settings().database_url)\nSessionLocal = sessionmaker(bind=engine)\n\ndef init_db():\n    Base.metadata.create_all(bind=engine)",
        }),
        evt(23.5, "verify_run", "VerifierAgent", {
            "command": "python -c \"from src.models import Base, SearchHistory; print('OK')\"",
            "exit_code": 0,
            "success": True,
            "duration_s": 0.6,
            "stdout": "OK\n",
            "stderr": "",
        }),
        evt(24.2, "task_end", "Orchestrator", {
            "task_id": "1.2",
            "task_name": "Set up database models",
            "success": True,
            "duration_s": 8.2,
        }),
        # Task 2.1 - with a failure + retry
        evt(24.5, "task_start", "Orchestrator", {
            "task_id": "2.1",
            "task_name": "Build weather API client",
            "phase": "Phase 2: Core Features",
            "files": ["src/weather.py", "tests/test_weather.py"],
        }),
        evt(25.0, "file_read", "ExecutorAgent", {
            "path": "src/config.py",
            "size_bytes": 380,
            "content_preview": "from pydantic_settings import BaseSettings...",
        }),
        evt(25.5, "llm_call", "ExecutorAgent", {
            "model": "gpt-4o",
            "prompt_tokens": 2400,
            "completion_tokens": 2100,
            "total_tokens": 4500,
            "duration_s": 7.2,
            "prompt_preview": "Generate code to complete this task:\n\n=== TASK ===\nID: 2.1\nName: Build weather API client\n\nAction:\nCreate an async HTTP client for OpenWeatherMap API...",
            "response_preview": "=== FILE: src/weather.py ===\n```python\nimport httpx\nfrom dataclasses import dataclass\nfrom src.config import get_settings\n\n@dataclass\nclass WeatherData:\n    city: str\n    temp_c: float\n    description: str\n    humidity: int\n    wind_speed: float\n    icon: str\n\nasync def get_current_weather(city: str) -> WeatherData:\n    settings = get_settings()\n    async with httpx.AsyncClient() as client:\n        resp = await client.get(\n            \"https://api.openweathermap.org/data/2.5/weather\",\n            params={\"q\": city, \"appid\": settings.openweather_api_key, \"units\": \"metric\"},\n        )\n        resp.raise_for_status()\n        data = resp.json()\n    ...\n```",
        }, duration_ms=7200),
        evt(32.8, "file_write", "ExecutorAgent", {
            "path": "src/weather.py",
            "size_bytes": 1240,
            "content_preview": "import httpx\nfrom dataclasses import dataclass\nfrom src.config import get_settings\n\n@dataclass\nclass WeatherData:\n    city: str\n    temp_c: float\n    description: str\n    humidity: int\n    wind_speed: float\n    icon: str",
        }),
        evt(33.0, "file_write", "ExecutorAgent", {
            "path": "tests/test_weather.py",
            "size_bytes": 890,
            "content_preview": "import pytest\nfrom unittest.mock import AsyncMock, patch\nfrom src.weather import get_current_weather, WeatherData\n\n@pytest.mark.asyncio\nasync def test_get_current_weather():\n    mock_response = {...}",
        }),
        # First verify fails
        evt(33.5, "verify_run", "VerifierAgent", {
            "command": "python -m pytest tests/test_weather.py -v",
            "exit_code": 1,
            "success": False,
            "duration_s": 2.1,
            "stdout": "tests/test_weather.py::test_get_current_weather FAILED\n\nE   ModuleNotFoundError: No module named 'src.config'",
            "stderr": "FAILED tests/test_weather.py::test_get_current_weather - ModuleNotFoundError",
        }),
        # Retry - second LLM call
        evt(35.8, "llm_call", "ExecutorAgent", {
            "model": "gpt-4o",
            "prompt_tokens": 2800,
            "completion_tokens": 1900,
            "total_tokens": 4700,
            "duration_s": 6.4,
            "prompt_preview": "The previous attempt failed with:\nModuleNotFoundError: No module named 'src.config'\n\nFix the test to use proper imports and mock the settings...",
            "response_preview": "=== FILE: tests/test_weather.py ===\n```python\nimport sys\nsys.path.insert(0, '.')\nimport pytest\nfrom unittest.mock import AsyncMock, patch, MagicMock\nfrom src.weather import get_current_weather, WeatherData\n...\n```",
        }, duration_ms=6400),
        evt(42.3, "file_write", "ExecutorAgent", {
            "path": "tests/test_weather.py",
            "size_bytes": 1120,
            "content_preview": "import sys\nsys.path.insert(0, '.')\nimport pytest\nfrom unittest.mock import AsyncMock, patch, MagicMock\nfrom src.weather import get_current_weather, WeatherData",
        }),
        # Second verify passes
        evt(42.8, "verify_run", "VerifierAgent", {
            "command": "python -m pytest tests/test_weather.py -v",
            "exit_code": 0,
            "success": True,
            "duration_s": 1.8,
            "stdout": "tests/test_weather.py::test_get_current_weather PASSED\n\n1 passed in 0.42s",
            "stderr": "",
        }),
        evt(44.7, "task_end", "Orchestrator", {
            "task_id": "2.1",
            "task_name": "Build weather API client",
            "success": True,
            "duration_s": 20.2,
            "retry_count": 1,
        }),
        # Workflow end
        evt(45.0, "workflow_end", "Orchestrator", {
            "success": True,
            "total_tasks": 3,
            "completed": 3,
            "failed": 0,
            "duration_s": 45.0,
        }),
    ]

    def _stream_events() -> None:
        """Write events with delays to simulate a live run."""
        import time as _time

        prev_t = 0.0
        for e in events:
            # Calculate delay from timestamp offsets
            offset = 0.0
            for k, v in e.items():
                if k == "timestamp":
                    try:
                        dt = datetime.fromisoformat(v)
                        offset = (dt - base).total_seconds()
                    except (ValueError, TypeError):
                        pass
            delay = min(max(offset - prev_t, 0.05), 2.0)  # cap delay at 2s for demo speed
            prev_t = offset
            _time.sleep(delay)
            with open(tmp, "a", encoding="utf-8") as f:
                f.write(json.dumps(e) + "\n")

    # Create empty file so server can start
    tmp.write_text("", encoding="utf-8")

    # Stream events in background thread
    t = threading.Thread(target=_stream_events, daemon=True)
    t.start()

    console.print("[bold cyan]Demo mode[/bold cyan] — streaming sample trace events")
    return tmp


@app.command()
def version() -> None:
    """Show sago version."""
    from sago import __version__

    console.print(f"[bold]sago[/bold] version {__version__}")


if __name__ == "__main__":
    app()
