"""sago judge command."""

from pathlib import Path

import typer
from rich.panel import Panel

from sago.commands import app, console

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
    if model.startswith("chatgpt/"):
        return "chatgpt"
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
            "Configure a separate LLM to review completed phases\nduring `sago replan`.",
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
            f"The judge will be used when `sago replan`\n"
            f"reviews completed phases.",
            title="Configuration Complete",
            border_style="green",
        )
    )


@app.command()
def judge() -> None:
    """Configure the judge LLM for post-phase code reviews."""
    try:
        _do_judge()
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None
