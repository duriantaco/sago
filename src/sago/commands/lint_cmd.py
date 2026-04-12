"""sago lint-plan command."""

from pathlib import Path

import typer

from sago.commands import app, console
from sago.core.parser import MarkdownParser
from sago.models.plan import Plan
from sago.validation import PlanValidator


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
