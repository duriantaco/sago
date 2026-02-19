# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development Commands

```bash
# Install
pip install -e .                     # Basic install
pip install -e ".[dev]"              # With dev tools (pytest, black, ruff, mypy)
pip install -e ".[all]"              # Full install (dev + compression)

# Run CLI
sago init [project-name]             # Initialize a new project
sago status [--path PATH]            # Show project status
sago plan [--path PATH]              # Generate PLAN.md from requirements
sago execute [--path PATH]           # Execute tasks from PLAN.md
sago run [--path PATH]               # Full workflow: plan + execute + verify
sago trace [--path PATH]             # Open dashboard for a past trace

# Key flags for `sago run`
#   --compress       Enable context compression
#   --cache/--no-cache  Smart caching (on by default)
#   --auto-retry     Auto-fix failed tasks
#   --trace          Open live dashboard in browser
#   --git-commit     Auto-commit after each task
#   --dry-run        Estimate cost without executing

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
- **`agents/`** -- Multi-agent orchestration system:
  - `base.py`: Abstract `BaseAgent` with LLM integration and optional context compression
  - `planner.py`: Generates PLAN.md from requirements
  - `executor.py`: Executes tasks (writes code), compresses context when enabled
  - `verifier.py`: Validates task completion
  - `orchestrator.py`: Coordinates plan->execute->verify workflow with caching and parallel/sequential execution
  - `dependencies.py`: `DependencyResolver` using topological sort for wave-based execution and circular dependency detection
  - `self_healing.py`: Recovery logic for failed tasks (--auto-retry)
- **`utils/`** -- LLM client (LiteLLM wrapper), context compression (SlidingWindow/LLMLingua/Passthrough strategies), smart task caching, git integration, cost estimation
- **`templates/`** -- 7 markdown templates (PROJECT, REQUIREMENTS, ROADMAP, STATE, PLAN, SUMMARY, IMPORTANT) generated on `sago init`

### Key Design Patterns

- **Async-first**: All agents use `async/await`; orchestrator can run independent tasks in parallel via asyncio (off by default)
- **Pydantic everywhere**: Config via `BaseSettings`, data models for tasks/phases/requirements
- **LiteLLM abstraction**: Multi-provider LLM support (OpenAI, Anthropic, Azure, etc.) with Tenacity retry logic
- **Wave-based execution**: `DependencyResolver` groups tasks into dependency-free waves; sequential by default, parallel opt-in

### Agent Workflow

1. `PlannerAgent` reads PROJECT.md + REQUIREMENTS.md -> generates PLAN.md with XML task structure
2. `DependencyResolver` analyzes tasks -> creates execution waves
3. `ExecutorAgent` processes each task (compresses context if --compress enabled)
4. `VerifierAgent` runs verification commands per task
5. `Orchestrator` coordinates all phases, manages caching, and STATE.md updates

### Integrated Features

- **Smart Caching** (`--cache`): Hashes task definition + file contents, skips re-execution on cache hit
- **Context Compression** (`--compress`): Opt-in, compresses LLM context via SlidingWindow before executor LLM calls
- **Auto-retry** (`--auto-retry`): Self-healing agent attempts to fix failed tasks

## Code Style

- Line length: 100 (Black + Ruff)
- Strict mypy: `disallow_untyped_defs`, `disallow_incomplete_defs`, `strict_equality`
- Ruff rules: E, W, F, I (isort), B (bugbear), C4 (comprehensions), UP (pyupgrade)
- `__init__.py` files are exempt from F401 (unused imports)
- Missing import stubs are ignored for: `litellm`

## Configuration

The app loads settings from environment variables / `.env` file. Key settings:
`LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `PLANNING_DIR` (default `.planning`), `ENABLE_GIT_COMMITS`, `ENABLE_PARALLEL_EXECUTION` (default false), `ENABLE_COMPRESSION` (default false), `MAX_CONTEXT_TOKENS` (default 100000), `LOG_LEVEL`
