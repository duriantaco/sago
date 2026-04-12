"""sago doctor command."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel
from rich.table import Table

from sago.commands import app, console, load_config, print_json_output
from sago.core.parser import MarkdownParser
from sago.core.project import ProjectManager
from sago.models.plan import Plan
from sago.state import StateManager
from sago.utils.agent_context import load_agent_context
from sago.validation import PlanValidator


def _check(name: str, status: str, message: str, **details: Any) -> dict[str, Any]:
    return {"name": name, "status": status, "message": message, "details": details}


def _run_doctor(project_path: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    project_exists = project_path.exists()
    checks.append(
        _check(
            "project_path",
            "pass" if project_exists else "fail",
            "Project path exists" if project_exists else "Project path does not exist",
            path=project_path,
        )
    )
    if not project_exists:
        return {
            "success": False,
            "project_path": project_path,
            "checks": checks,
            "summary": {"pass": 0, "warn": 0, "fail": 1},
            "overall_status": "fail",
        }

    cfg = load_config(project_path, create_dirs=False)
    manager = ProjectManager(cfg)
    parser = MarkdownParser()

    is_sago_project = manager.is_sago_project(project_path)
    checks.append(
        _check(
            "project_files",
            "pass" if is_sago_project else "fail",
            (
                "PROJECT.md and REQUIREMENTS.md are present"
                if is_sago_project
                else "Missing PROJECT.md and/or REQUIREMENTS.md"
            ),
        )
    )

    llm_ready = bool(cfg.llm_api_key or cfg.is_chatgpt_subscription)
    checks.append(
        _check(
            "llm_config",
            "pass" if llm_ready else "warn",
            (
                f"LLM configured for provider '{cfg.llm_provider}'"
                if llm_ready
                else f"No LLM API key configured for provider '{cfg.llm_provider}'"
            ),
            provider=cfg.llm_provider,
            model=cfg.llm_model,
        )
    )

    agent_context = load_agent_context(project_path)
    if agent_context.errors:
        checks.append(
            _check(
                "agent_context",
                "warn",
                (
                    f"Detected {len(agent_context.files)} agent context file(s) "
                    f"with {len(agent_context.errors)} read warning(s)"
                ),
                files=[entry.to_summary_dict() for entry in agent_context.files],
                errors=agent_context.errors,
            )
        )
    elif agent_context.present:
        checks.append(
            _check(
                "agent_context",
                "pass",
                f"Detected {len(agent_context.files)} agent context file(s)",
                files=[entry.to_summary_dict() for entry in agent_context.files],
            )
        )
    else:
        checks.append(
            _check(
                "agent_context",
                "warn",
                (
                    "No repo-local agent context files detected "
                    "(IMPORTANT.md, AGENTS.md, SKILLS.md, CLAUDE.md, .cursorrules)"
                ),
            )
        )

    try:
        import keyring

        backend = type(keyring.get_keyring()).__name__
        keyring.get_password("sago", "__doctor_probe__")
        checks.append(
            _check(
                "keyring",
                "pass",
                f"Keyring backend available: {backend}",
            )
        )
    except Exception as exc:
        checks.append(
            _check(
                "keyring",
                "warn",
                f"Keyring unavailable: {exc}",
            )
        )

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        in_repo = result.returncode == 0 and result.stdout.strip() == "true"
        checks.append(
            _check(
                "git",
                "pass" if in_repo else "warn",
                "Inside a git work tree" if in_repo else "Not inside a git work tree",
            )
        )
    except (OSError, subprocess.SubprocessError) as exc:
        checks.append(_check("git", "warn", f"Git check failed: {exc}"))

    dashboard_asset = Path(__file__).resolve().parent.parent / "web" / "mission_control.html"
    checks.append(
        _check(
            "dashboard_asset",
            "pass" if dashboard_asset.exists() else "fail",
            (
                "mission_control.html is available"
                if dashboard_asset.exists()
                else "mission_control.html is missing"
            ),
            path=dashboard_asset,
        )
    )

    plan_file = project_path / "PLAN.md"
    if not plan_file.exists():
        checks.append(_check("plan", "warn", "PLAN.md not found"))
    else:
        try:
            plan_content = plan_file.read_text(encoding="utf-8")
            phases = parser.parse_xml_tasks(plan_content)
            validation = PlanValidator().validate(Plan(phases=phases))
            if validation.valid and not validation.warnings:
                checks.append(
                    _check(
                        "plan",
                        "pass",
                        "PLAN.md parses and validates cleanly",
                        phase_count=len(phases),
                        task_count=sum(len(phase.tasks) for phase in phases),
                    )
                )
            elif validation.valid:
                checks.append(
                    _check(
                        "plan",
                        "warn",
                        f"PLAN.md is valid with {len(validation.warnings)} warning(s)",
                        warnings=[issue.message for issue in validation.warnings],
                    )
                )
            else:
                checks.append(
                    _check(
                        "plan",
                        "fail",
                        f"PLAN.md has {len(validation.errors)} validation error(s)",
                        errors=[issue.message for issue in validation.errors],
                    )
                )
        except Exception as exc:
            checks.append(_check("plan", "fail", f"PLAN.md could not be parsed: {exc}"))

    state_file = project_path / "STATE.md"
    if not state_file.exists():
        checks.append(_check("state", "warn", "STATE.md not found"))
    else:
        state_result = StateManager(state_file).validate()
        checks.append(
            _check(
                "state",
                "pass" if state_result.valid else "warn",
                (
                    "STATE.md format looks good"
                    if state_result.valid
                    else "STATE.md has format warnings"
                ),
                warnings=state_result.warnings,
            )
        )

    summary = {
        "pass": sum(1 for check in checks if check["status"] == "pass"),
        "warn": sum(1 for check in checks if check["status"] == "warn"),
        "fail": sum(1 for check in checks if check["status"] == "fail"),
    }
    overall_status = "fail" if summary["fail"] else "warn" if summary["warn"] else "pass"
    return {
        "success": summary["fail"] == 0,
        "project_path": project_path,
        "checks": checks,
        "summary": summary,
        "overall_status": overall_status,
    }


def _render_doctor(payload: dict[str, Any]) -> None:
    console.print(Panel(f"[bold]{payload['project_path']}[/bold]", title="sago doctor"))
    table = Table(show_header=True)
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    table.add_column("Message")

    style_map = {"pass": "green", "warn": "yellow", "fail": "red"}
    for check in payload["checks"]:
        status = check["status"]
        styled = f"[{style_map.get(status, 'dim')}]{status}[/{style_map.get(status, 'dim')}]"
        table.add_row(check["name"], styled, check["message"])
    console.print(table)

    summary = payload["summary"]
    console.print(
        f"\n[bold]Summary:[/bold] "
        f"[green]{summary['pass']} pass[/green], "
        f"[yellow]{summary['warn']} warn[/yellow], "
        f"[red]{summary['fail']} fail[/red]"
    )


@app.command(name="doctor")
def doctor(
    project_path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Project path"),
    json_output: bool = typer.Option(False, "--json", help="Output structured JSON"),
) -> None:
    """Run environment and project diagnostics."""
    payload = _run_doctor(project_path)
    if json_output:
        print_json_output(payload)
    else:
        _render_doctor(payload)
    raise typer.Exit(1 if payload["summary"]["fail"] else 0)
