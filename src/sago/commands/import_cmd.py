"""sago import command — onboard an existing codebase."""

import asyncio
import subprocess
from pathlib import Path

import typer
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from sago.commands import app, check_llm_configured, console, load_config
from sago.core.project import ProjectManager


def _gather_codebase_context(project_path: Path) -> dict[str, str]:
    """Collect signals from the existing codebase for the LLM."""
    from sago.utils.environment import detect_environment, format_environment_context
    from sago.utils.repo_map import generate_repo_map

    context: dict[str, str] = {}

    # Repo map (class/function signatures)
    repo_map = generate_repo_map(project_path, max_files=150, max_chars=12000)
    if repo_map:
        context["repo_map"] = repo_map

    # Environment
    env = detect_environment()
    context["environment"] = format_environment_context(env)

    # Config files — read the first 3000 chars of each
    config_files = [
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "Makefile",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        ".env.example",
        "requirements.txt",
        "requirements-dev.txt",
    ]
    found_configs: list[str] = []
    for name in config_files:
        fpath = project_path / name
        if fpath.exists():
            try:
                text = fpath.read_text(encoding="utf-8")[:3000]
                found_configs.append(f"--- {name} ---\n{text}")
            except (OSError, UnicodeDecodeError):
                pass
    if found_configs:
        context["config_files"] = "\n\n".join(found_configs)

    # README (if present — valuable project context)
    for readme_name in ["README.md", "README.rst", "README.txt", "README"]:
        readme_path = project_path / readme_name
        if readme_path.exists():
            try:
                context["readme"] = readme_path.read_text(encoding="utf-8")[:6000]
                break
            except (OSError, UnicodeDecodeError):
                pass

    # Directory structure (top 2 levels)
    tree_lines: list[str] = []
    _walk_tree(project_path, tree_lines, depth=0, max_depth=2)
    if tree_lines:
        context["directory_structure"] = "\n".join(tree_lines[:200])

    # Git log (recent commits for project context)
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-20"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            context["recent_commits"] = result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass

    return context


_SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".planning",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
    "htmlcov",
    ".egg-info",
    ".eggs",
}


def _walk_tree(path: Path, lines: list[str], depth: int, max_depth: int) -> None:
    """Build a simple directory tree."""
    if depth > max_depth:
        return
    indent = "  " * depth
    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return
    for entry in entries:
        if entry.name.startswith(".") and entry.name not in {".env.example"}:
            if entry.is_dir():
                continue
            # skip hidden files too
            continue
        if entry.is_dir():
            if entry.name in _SKIP_DIRS or entry.name.endswith(".egg-info"):
                continue
            lines.append(f"{indent}{entry.name}/")
            _walk_tree(entry, lines, depth + 1, max_depth)
        else:
            lines.append(f"{indent}{entry.name}")


def _do_import(
    project_path: Path,
    overwrite: bool,
    yes: bool,
    requirements_hint: str | None,
) -> None:
    cfg = load_config(project_path)
    check_llm_configured(cfg)

    manager = ProjectManager(cfg)

    # Check if already a sago project
    existing = [f for f in ProjectManager.TEMPLATE_FILES if (project_path / f).exists()]
    if existing and not overwrite:
        console.print(
            Panel(
                "[bold yellow]This directory already has sago files:[/bold yellow]\n"
                + "".join(f"  - {f}\n" for f in existing)
                + "\nUse --overwrite to replace them.",
                title="Already Initialized",
                border_style="yellow",
            )
        )
        if not yes and not typer.confirm("Overwrite existing sago files?"):
            raise typer.Exit(0)

    console.print("[bold blue]Scanning codebase...[/bold blue]")
    codebase_context = _gather_codebase_context(project_path)

    if not codebase_context.get("repo_map") and not codebase_context.get("config_files"):
        console.print(
            "[yellow]Warning: Could not find much code to analyze. "
            "Make sure you're pointing at the right directory.[/yellow]"
        )
        if not yes and not typer.confirm("Continue anyway?"):
            raise typer.Exit(0)

    # Set up sago scaffolding (creates .planning/, STATE.md, IMPORTANT.md, CLAUDE.md)
    manager.init_project(project_path, project_name=project_path.name, overwrite=True)

    # Generate PROJECT.md + REQUIREMENTS.md from codebase analysis
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        progress.add_task(description="Analyzing codebase and generating project files...", total=None)
        asyncio.run(
            manager.generate_from_codebase(
                codebase_context,
                project_path,
                project_path.name,
                requirements_hint=requirements_hint,
            )
        )

    console.print("\n[green]Codebase imported successfully![/green]\n")

    # Show what was generated
    for filename in ["PROJECT.md", "REQUIREMENTS.md"]:
        fpath = project_path / filename
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8")
            line_count = len(content.splitlines())
            console.print(f"  [cyan]{filename}[/cyan] ({line_count} lines)")

    console.print("  [dim].planning/[/dim] directory ready")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Review and edit PROJECT.md and REQUIREMENTS.md")
    console.print("  2. Run: sago plan")
    console.print("  3. Point your coding agent at the project")


@app.command(name="import")
def import_cmd(
    project_path: Path = typer.Option(
        Path.cwd(), "--path", "-p", help="Path to existing codebase"
    ),
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite existing sago files"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive mode"),
    requirements: str | None = typer.Option(
        None,
        "--requirements",
        "-r",
        help="Hint about what you want to build next (guides REQUIREMENTS.md generation)",
    ),
) -> None:
    """Import an existing codebase into sago.

    Analyzes the project structure, config files, and code signatures to
    generate PROJECT.md and REQUIREMENTS.md automatically. Removes the
    cold-start problem — no need to write these files from scratch.
    """
    try:
        _do_import(project_path.resolve(), overwrite, yes, requirements_hint=requirements)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None
