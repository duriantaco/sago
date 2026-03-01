# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What sago is

Sago is a **planning and orchestration tool** for AI coding agents. It generates structured project plans from requirements, then hands off execution to a real coding agent (Claude Code, Cursor, Aider, etc.). Sago is the project manager, not the developer.

**Core flow:** `sago init` -> `sago plan` -> coding agent executes PLAN.md -> `sago status` to track

## Build & Development Commands

```bash
# Install
pip install -e .                     # Basic install
pip install -e ".[dev]"              # With dev tools (pytest, black, ruff, mypy)
pip install -e ".[all]"              # Full install (dev + compression)

# Run CLI
sago init [project-name]             # Initialize a new project (generates CLAUDE.md for the coding agent)
sago plan [--path PATH]              # Generate PLAN.md from requirements
sago status [--path PATH]            # Show project status
sago trace [--path PATH]             # Open dashboard for a past trace

# Test
pytest                               # Run all tests (includes coverage by default)
pytest tests/test_parser.py -v       # Single test file
pytest tests/test_parser.py::test_name -v  # Single test
pytest -x                            # Stop on first failure

# Code quality
black src/ tests/                    # Format (line-length=100)
ruff check src/                      # Lint
mypy src/                            # Type check (strict mode)
```

## Architecture

**Python 3.11+ project** using `src/` layout with package at `src/sago/`.

### Module Structure

- **`cli.py`** -- Typer CLI app, entry point via `sago = "sago.cli:app"`
- **`core/`** -- Configuration (Pydantic BaseSettings with `.env`), markdown/XML parsing, project template initialization
- **`agents/`** -- Planning and orchestration:
  - `base.py`: Abstract `BaseAgent` with LLM integration and optional context compression
  - `planner.py`: Generates PLAN.md from requirements (env-aware, suggests dependencies)
  - `orchestrator.py`: Coordinates the planning and replan workflows
  - `replanner.py`: Surgically updates PLAN.md based on feedback while preserving completed work
  - `reviewer.py`: Reviews generated code quality post-phase
- **`utils/`** -- LLM client (LiteLLM wrapper), environment detection, context compression, smart task caching, git integration, repo map generation
- **`templates/`** -- Markdown templates (PROJECT, REQUIREMENTS, STATE, PLAN, IMPORTANT, CLAUDE) generated on `sago init`

### Key Design Patterns

- **Async-first**: All agents use `async/await`
- **Pydantic everywhere**: Config via `BaseSettings`, data models for tasks/phases/requirements
- **LiteLLM abstraction**: Multi-provider LLM support (OpenAI, Anthropic, Azure, etc.) with Tenacity retry logic
- **Planning is the product**: Sago's value is in generating good PLAN.md files, not in executing them

### Agent Workflow

1. `PlannerAgent` reads PROJECT.md + REQUIREMENTS.md + environment -> generates PLAN.md with XML task structure
2. External coding agent (Claude Code, Cursor, etc.) executes tasks following PLAN.md
3. `sago status` tracks progress via STATE.md (including resume point)
4. `sago replan` updates PLAN.md based on feedback, preserving completed work

## Code Style

- Line length: 100 (Black + Ruff)
- Strict mypy: `disallow_untyped_defs`, `disallow_incomplete_defs`, `strict_equality`
- Ruff rules: E, W, F, I (isort), B (bugbear), C4 (comprehensions), UP (pyupgrade)
- `__init__.py` files are exempt from F401 (unused imports)
- Missing import stubs are ignored for: `litellm`

## Configuration

The app loads settings from environment variables / `.env` file. Key settings:
`LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `PLANNING_DIR` (default `.planning`), `LOG_LEVEL`
