"""sago init command."""

import asyncio
from pathlib import Path

import typer
from rich.panel import Panel

from sago.commands import app, check_llm_configured, console, load_config
from sago.core.project import ProjectManager


def _do_init(
    project_name: str | None,
    path: Path | None,
    overwrite: bool,
    prompt: str | None = None,
    yes: bool = False,
) -> None:
    cfg = load_config()
    is_tty = console.is_terminal

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
    manager = ProjectManager(cfg)
    manager.init_project(project_path, project_name=project_name, overwrite=overwrite)

    prompt_succeeded = False
    if prompt:
        console.print("[dim]Generating project files from prompt...[/dim]")
        try:
            check_llm_configured(cfg)
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
    except typer.Exit:
        raise
    except FileExistsError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None
