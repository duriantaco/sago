"""sago plan command."""

import asyncio
from pathlib import Path

import typer
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from sago.agents.orchestrator import PlanningWorkflow
from sago.commands import (
    app,
    check_llm_configured,
    console,
    load_config,
    print_json_output,
    show_plan_summary,
    show_validation_results,
)
from sago.core.parser import MarkdownParser
from sago.core.project import ProjectManager
from sago.models.plan import Plan
from sago.utils.agent_context import load_agent_context
from sago.validation import PlanValidator

# Distinctive strings from the placeholder templates
_PLACEHOLDER_MARKERS = [
    "A brief description of what you're building and why",
    "TaskFlow is a CLI task runner",
    "Each requirement becomes one or more tasks in the plan",
    "Parse YAML job files with `name`, `command`, `depends_on`",
]


def check_placeholder_content(project_path: Path, auto_continue: bool = False) -> list[str]:
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
        return []

    if auto_continue:
        return files_with_placeholders

    console.print(
        Panel(
            "[bold yellow]The following files still contain placeholder/example content:"
            "[/bold yellow]\n"
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
    return files_with_placeholders


def _prompt_plan_acceptance(plan_file: Path, old_plan_backup: str | None) -> None:
    """Prompt user to accept/reject a generated plan. Raises typer.Exit on rejection."""
    if typer.confirm("\nAccept this plan?", default=True):
        return
    if old_plan_backup is not None:
        plan_file.write_text(old_plan_backup, encoding="utf-8")
        console.print("[dim]Plan reverted to previous version.[/dim]")
    else:
        plan_file.unlink()
        console.print("[dim]Plan rejected and removed.[/dim]")
    raise typer.Exit(0)


def _build_plan_payload(project_path: Path) -> dict[str, object]:
    parser = MarkdownParser()
    plan_file = project_path / "PLAN.md"
    phases = parser.parse_xml_tasks(plan_file.read_text(encoding="utf-8"))
    dependencies = parser.parse_dependencies(plan_file.read_text(encoding="utf-8"))
    validation = PlanValidator().validate(Plan(phases=phases))
    agent_context = load_agent_context(project_path).to_summary_dict()
    return {
        "success": True,
        "project_path": project_path,
        "plan_path": plan_file,
        "agent_context": agent_context,
        "phase_count": len(phases),
        "task_count": sum(len(phase.tasks) for phase in phases),
        "dependencies": dependencies,
        "phases": [phase.to_dict() for phase in phases],
        "validation": {
            "valid": validation.valid,
            "errors": len(validation.errors),
            "warnings": len(validation.warnings),
            "suggestions": len(validation.suggestions),
        },
    }


def _do_plan(
    project_path: Path, force: bool, auto_accept: bool = False, json_output: bool = False
) -> dict[str, object]:
    cfg = load_config(project_path)
    manager = ProjectManager(cfg)

    if project_path.exists() and manager.has_any_required_files(project_path):
        missing = manager.missing_required_files(project_path)
        if missing:
            raise ValueError(f"Missing required files: {', '.join(missing)}")

    if not manager.is_sago_project(project_path):
        raise ValueError(f"Not a sago project: {project_path}")

    check_llm_configured(cfg)

    plan_file = project_path / "PLAN.md"
    old_plan_backup = None
    if plan_file.exists():
        if not force:
            if json_output:
                raise ValueError("PLAN.md already exists. Re-run with --force to overwrite it.")
            if not typer.confirm("Overwrite?"):
                raise typer.Exit(0)
        old_plan_backup = plan_file.read_text(encoding="utf-8")

    placeholder_files = check_placeholder_content(
        project_path, auto_continue=auto_accept or json_output
    )
    agent_context = load_agent_context(project_path).to_summary_dict()

    orchestrator = PlanningWorkflow(config=cfg)

    if json_output:
        result = asyncio.run(
            orchestrator.run_workflow(
                project_path=project_path,
                plan=True,
            )
        )
    else:
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

    if not result.success:
        raise ValueError(f"Plan generation failed: {result.error}")

    payload = _build_plan_payload(project_path)
    payload["placeholder_files"] = placeholder_files
    if json_output:
        return payload

    console.print("\n[green]Plan generated successfully![/green]")
    console.print(f"   {plan_file}\n")
    if agent_context["present"]:
        file_list = ", ".join(entry["path"] for entry in agent_context["files"])
        console.print(f"[bold]Agent context used:[/bold] {file_list}\n")

    show_plan_summary(project_path)

    parser = MarkdownParser()
    try:
        phases = parser.parse_xml_tasks(plan_file.read_text(encoding="utf-8"))
        show_validation_results(phases)

        if not auto_accept:
            _prompt_plan_acceptance(plan_file, old_plan_backup)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[yellow]Could not validate plan: {e}[/yellow]")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("   1. Review PLAN.md")
    console.print("   2. Point your coding agent at the project")
    console.print("      Claude Code reads CLAUDE.md automatically")
    return payload


@app.command()
def plan(
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing PLAN.md"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-accept plan without confirmation"),
    json_output: bool = typer.Option(False, "--json", help="Output structured JSON"),
) -> None:
    """Generate PLAN.md from requirements and project context."""
    try:
        payload = _do_plan(project_path, force, auto_accept=yes or json_output, json_output=json_output)
        if json_output:
            print_json_output(payload)
            return
    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            print_json_output({"success": False, "error": str(e)})
            raise typer.Exit(1) from None
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None
