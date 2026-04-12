"""sago watch command."""

from pathlib import Path

import typer

from sago.commands import app, console, load_config
from sago.core.parser import MarkdownParser
from sago.core.project import ProjectManager


def _do_watch(project_path: Path, port: int) -> None:
    import time

    from sago.web.server import start_watch_server
    from sago.web.watcher import ProjectWatcher

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

    trace_path = project_path / cfg.planning_dir / "trace.jsonl"

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
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None
