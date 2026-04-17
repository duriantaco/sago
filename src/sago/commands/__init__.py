"""sago CLI command package — shared state, config, and display helpers."""

import json
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sago.core.config import Config, find_dotenv
from sago.core.parser import MarkdownParser
from sago.models.execution import ExecutionHistory
from sago.models import Phase
from sago.models.plan import Plan
from sago.models.state import PhaseGateStatus, PhaseReview, ProjectState, TaskState, TaskStatus
from sago.recommendations import RecommendationEngine
from sago.validation import PlanValidator

app = typer.Typer(
    name="sago",
    help="sago - AI project planning for coding agents",
    add_completion=False,
)

console = Console()

# Lazy config — created on first access so that ``import sago.cli`` has no
# filesystem side effects (Config.model_post_init creates .planning/).
# NOTE: This global singleton assumes single-threaded CLI execution.  If sago
# ever gains concurrent command execution or parallel test runners that share
# the same process, this will need to be replaced with a context-local store.
_config: Config | None = None


def _project_relative_path(project_path: Path, value: Path | None) -> Path | None:
    if value is None or value.is_absolute():
        return value
    return (project_path / value).resolve()


def _finalize_project_config(cfg: Config, project_path: Path, *, create_dirs: bool) -> Config:
    cfg.planning_dir = _project_relative_path(project_path, cfg.planning_dir) or cfg.planning_dir
    cfg.log_file = _project_relative_path(project_path, cfg.log_file)
    cfg.trace_file = _project_relative_path(project_path, cfg.trace_file)

    if create_dirs:
        cfg.planning_dir.mkdir(parents=True, exist_ok=True)
        if cfg.log_file:
            cfg.log_file.parent.mkdir(parents=True, exist_ok=True)
        if cfg.trace_file:
            cfg.trace_file.parent.mkdir(parents=True, exist_ok=True)

    return cfg


def load_config(project_path: Path | None = None, *, create_dirs: bool = True) -> Config:
    """Create a Config, searching for .env from *project_path* upwards."""
    global _config
    if project_path is not None:
        project_root = project_path.resolve()
        env_file = find_dotenv(project_root) or ".env"
        cfg = Config(_env_file=env_file, create_dirs=False)  # type: ignore[call-arg]
        _config = _finalize_project_config(cfg, project_root, create_dirs=create_dirs)
    elif _config is None:
        _config = Config(create_dirs=create_dirs)
    return _config


def get_config() -> Config:
    """Return the current Config (set by the last ``load_config`` call)."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def _json_default(value: Any) -> Any:
    """Serialize common CLI payload types to JSON-friendly values."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def print_json_output(data: Any) -> None:
    """Print structured JSON for agent-facing command output."""
    typer.echo(json.dumps(data, indent=2, default=_json_default))


# Provider-specific env vars that litellm checks automatically
PROVIDER_KEY_ENV_VARS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "azure": "AZURE_API_KEY",
    "cohere": "COHERE_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY",
    "together_ai": "TOGETHERAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}


def check_llm_configured(cfg: Config | None = None) -> None:
    """Fail early if no LLM API key is available."""
    cfg = cfg or get_config()
    if cfg.llm_api_key:
        return
    if cfg.is_chatgpt_subscription:
        return
    provider_env = PROVIDER_KEY_ENV_VARS.get(cfg.llm_provider, "")
    console.print(
        Panel(
            f"[bold red]No API key configured for LLM provider "
            f"'{cfg.llm_provider}'[/bold red]\n\n"
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


def show_recommendations(
    phases: list[Phase],
    task_states: list[TaskState],
    execution_history: ExecutionHistory | None = None,
    phase_reviews: dict[str, PhaseReview] | None = None,
) -> None:
    """Evaluate and display recommendations based on plan + state."""
    plan = Plan(phases=phases)
    state = ProjectState(task_states=task_states, phase_reviews=phase_reviews or {})
    engine = RecommendationEngine()
    recs = engine.evaluate(plan, state, execution_history)

    if not recs:
        return

    style_map = {
        "suggest_replan": "yellow",
        "warn_repeated_failure": "red",
        "warn_missing_evidence": "yellow",
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


def summarize_evidence(
    state: ProjectState | None,
    execution_history: ExecutionHistory | None,
) -> dict[str, int]:
    """Build a concise evidence summary for builder-facing JSON payloads."""
    receipts = len(execution_history.records) if execution_history is not None else 0
    repeated_failures = (
        len(execution_history.repeated_failures()) if execution_history is not None else 0
    )
    if state is None or execution_history is None:
        return {
            "receipts": receipts,
            "verified_done": 0,
            "missing_done": 0,
            "repeated_failures": repeated_failures,
        }

    completed = state.completed_task_ids()
    verified_done = execution_history.tasks_with_successful_receipts()
    return {
        "receipts": receipts,
        "verified_done": len(completed & verified_done),
        "missing_done": len(completed - verified_done),
        "repeated_failures": repeated_failures,
    }


def summarize_memory(state: ProjectState | None) -> dict[str, Any]:
    """Build a deterministic summary of the currently available project memory."""
    if state is None:
        return {
            "decision_count": 0,
            "blocker_count": 0,
            "reviewed_phase_count": 0,
            "decisions": [],
            "blockers": [],
            "reviewed_phases": [],
        }

    reviewed_phases = sorted(state.phase_reviews)
    return {
        "decision_count": len(state.decisions),
        "blocker_count": len(state.blockers),
        "reviewed_phase_count": len(reviewed_phases),
        "decisions": list(state.decisions),
        "blockers": list(state.blockers),
        "reviewed_phases": reviewed_phases,
    }


def serialize_state_for_builder(state: ProjectState | None) -> dict[str, Any] | None:
    """Return a stable builder-facing state payload."""
    if state is None:
        return None

    return {
        "active_phase": state.active_phase,
        "current_task": state.current_task,
        "task_states": [task_state.model_dump(mode="json") for task_state in state.task_states],
        "decisions": list(state.decisions),
        "blockers": list(state.blockers),
        "resume_point": state.resume_point.model_dump(mode="json") if state.resume_point else None,
        "phase_reviews": {
            phase_name: {
                "phase_name": review.phase_name,
                "summary": review.summary,
                "gate_status": review.gate_status.value,
                "reviewed_at": review.reviewed_at,
                "reviewer": review.reviewer,
                "finding_count": len(review.findings),
                "findings": [finding.model_dump(mode="json") for finding in review.findings],
            }
            for phase_name, review in state.phase_reviews.items()
        },
    }


def show_validation_results(phases: list[Phase]) -> bool:
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


def show_plan_summary(project_path: Path) -> list[str]:
    """Read PLAN.md, display phase/task summary and dependencies. Returns dependency list."""
    parser = MarkdownParser()
    plan_file = project_path / "PLAN.md"
    content = plan_file.read_text(encoding="utf-8")

    phases = parser.parse_xml_tasks(content)
    dependencies = parser.parse_dependencies(content)

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

    if dependencies:
        dep_text = "\n".join(f"  - {dep}" for dep in dependencies)
        console.print(Panel(dep_text, title="Dependencies", border_style="blue"))

    return dependencies


def get_phase_status(phases: list[Phase], task_states: list[TaskState]) -> list[dict[str, Any]]:
    """Group task states by phase, returning per-phase status.

    Returns list of dicts: {name, done, failed, skipped, pending, total, status}
    where status is 'complete', 'partial', or 'pending'.
    """
    state_by_id = {ts.task_id: ts.status.value for ts in task_states}
    result: list[dict[str, Any]] = []
    for phase in phases:
        done = sum(1 for t in phase.tasks if state_by_id.get(t.id) == "done")
        failed = sum(1 for t in phase.tasks if state_by_id.get(t.id) == "failed")
        skipped = sum(1 for t in phase.tasks if state_by_id.get(t.id) == "skipped")
        pending = len(phase.tasks) - done - failed - skipped
        if pending == 0 and failed == 0:
            status = "complete"
        elif done > 0 or failed > 0 or skipped > 0:
            status = "partial"
        else:
            status = "pending"
        result.append(
            {
                "name": phase.name,
                "done": done,
                "failed": failed,
                "skipped": skipped,
                "pending": pending,
                "total": len(phase.tasks),
                "status": status,
            }
        )
    return result


def get_phase_gates(phases: list[Phase], state: ProjectState) -> list[dict[str, Any]]:
    """Return gate status for completed phases."""
    state_by_id = {ts.task_id: ts.status.value for ts in state.task_states}
    gates: list[dict[str, Any]] = []
    for phase in phases:
        done = sum(1 for t in phase.tasks if state_by_id.get(t.id) == "done")
        failed = sum(1 for t in phase.tasks if state_by_id.get(t.id) == "failed")
        skipped = sum(1 for t in phase.tasks if state_by_id.get(t.id) == "skipped")
        pending = len(phase.tasks) - done - failed - skipped
        if pending != 0 or failed != 0:
            continue

        review = state.phase_reviews.get(phase.name)
        gate_status = review.gate_status if review is not None else PhaseGateStatus.PENDING_REVIEW
        gates.append(
            {
                "phase_name": phase.name,
                "status": gate_status.value,
                "reviewed_at": review.reviewed_at if review is not None else None,
                "blocking_findings": [
                    finding.model_dump(mode="json") for finding in (review.blocking_findings() if review else [])
                ],
                "summary": review.summary if review is not None else "",
            }
        )
    return gates


# ---------------------------------------------------------------------------
# version command (trivial — lives here)
# ---------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Show sago version."""
    from sago import __version__

    console.print(f"[bold]sago[/bold] version {__version__}")


# ---------------------------------------------------------------------------
# Register command modules — imports must be at the bottom to avoid circular
# imports, since the command modules import ``app`` (and other names) from
# this package.
# ---------------------------------------------------------------------------
from sago.commands import (  # noqa: E402, F401
    checkpoint_cmd,
    doctor_cmd,
    import_cmd,
    init_cmd,
    judge_cmd,
    lint_cmd,
    next_cmd,
    plan_cmd,
    replan_cmd,
    status_cmd,
    watch_cmd,
)
