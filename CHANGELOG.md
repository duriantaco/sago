# Changelog

## [0.2.1] - 2026-03-01

### Added
- **`depends_on` task dependencies** — tasks now support an optional `depends_on="id1,id2"` XML attribute for declaring explicit dependencies between tasks, enabling DAG-based plans where independent tasks within a phase can run in parallel. Omitting `depends_on` preserves the current sequential-by-default behavior. Parsed into `Task.depends_on: list[str]`, shown in replan diffs, and documented in planner/replanner LLM prompts and the CLAUDE.md coding agent template.
- **Resume Point in STATE.md** — new `## Resume Point` section tracks last completed task, next task, failure reason, and git checkpoint tag so coding agents can resume without re-reading the full plan
- **`ResumePoint` dataclass + parser** — `parse_resume_point()` on `MarkdownParser`; `parse_state()` now includes `resume_point` key
- **Resume point in `sago status`** — color-coded table (green/yellow/red/cyan) shown when a resume point exists
- **Resume context in replanner** — `_build_state_summary()` appends resume point details so the LLM has retry context when replanning
- **CLAUDE.md template updated** — instructs coding agents to maintain the resume point and create `sago-checkpoint-{task_id}` git tags
- **Non-interactive replan** — `sago replan -f "feedback text" -y` passes feedback and auto-applies changes without prompts, enabling scripted and agent-driven replanning
- **LLM token threshold warnings** — `LLMClient` now estimates input token count before each call and logs a warning when it exceeds `warn_token_threshold` (default 50k tokens)
- **LLM usage logging** — prompt, completion, and total token counts logged after every LLM call; `BaseAgent._call_llm()` includes the breakdown in its response log
- **PLAN.md template expanded** — XML schema now includes `<dependencies>` block for package dependencies with version constraints and `<review>` block with post-phase code review instructions
- **Shared test fixtures** — new `tests/conftest.py` with `SAMPLE_XML`, `SAMPLE_PLAN`, `SAMPLE_STATE` constants and `sago_project` / `sago_project_with_plan` fixtures for temp project directories
- **CLI unit tests** — new `tests/test_cli.py` covering `version`, `init`, `plan`, `status`, and `replan` commands using Typer's `CliRunner`
- **Integration tests** — new `tests/test_integration.py` with end-to-end workflows (init → plan → status, replan one-shot) using mocked LLM responses

### Changed
- **CLAUDE.md (sago repo)** — rewritten to reflect planning-first identity; removed executor, verifier, self-healing, and parallel execution references; added "Planning is the product" as a key design pattern

### Removed
- **`DependencyResolver`** — topological-sort wave scheduler removed from `agents/dependencies.py`; unnecessary now that external coding agents execute tasks sequentially from PLAN.md
- **`CostEstimator`** — per-model token pricing and workflow cost estimation removed from `utils/cost_estimator.py`; execution costs are the external agent's concern, not sago's
- **Tests for removed modules** — `tests/test_dependencies.py` (12 tests) and `tests/test_cost_estimator.py` (14 tests) deleted

## [0.2.0] - 2026-02-21

### Added
- **Phase gate in `sago replan`** — replan now acts as a phase gate between phases. It reviews completed work via `ReviewerAgent`, displays findings (CRITICAL/WARNING/SUGGESTION), writes a phase summary to STATE.md, and optionally replans with full code context
- **`Orchestrator.run_review()`** — new method that runs the `ReviewerAgent` on a completed phase using the judge model config
- **Review context in replanning** — `run_replan_workflow()` and `ReplannerAgent` now accept `review_context` and `repo_map` strings, giving the LLM awareness of actual code and review feedback when updating the plan
- **Repo map in replanner** — `ReplannerAgent` now generates and includes an aider-style repo map (class/function signatures) in its project context, matching the planner's behavior
- **Corrective task rule** — replanner prompt now instructs the LLM to add NEW corrective tasks (with new IDs) when review finds issues in completed tasks, rather than modifying done tasks
- **Live markdown viewer in mission control** — `sago watch` now displays real-time rendered content of project .md files (PLAN.md, STATE.md, PROJECT.md, REQUIREMENTS.md) in a tabbed viewer alongside the task progress panel
- **`sago replan` command** — update PLAN.md based on natural language feedback without regenerating from scratch. Preserves completed tasks, shows a diff summary (added/modified/removed tasks), and prompts for confirmation before applying changes
- **`ReplannerAgent`** — new agent that takes the current plan XML, task states from STATE.md, and user feedback, then asks the LLM to surgically update the plan while preserving completed work
- **`Orchestrator.run_replan_workflow()`** — orchestrates the replan flow with tracing support
- **Mission control dashboard** — `sago watch` launches a live webapp that monitors your coding agent's progress in real time. Dark-themed UI with phase tree, task checklist, file activity feed, dependency list, and per-phase progress bars. Polls STATE.md every second — no new dependencies (stdlib HTTP server + `os.stat`)
- **`parse_state_tasks()` on MarkdownParser** — structured parsing of STATE.md that cross-references with PLAN.md phases, returning full status objects (done/failed/pending) for every task
- **`ProjectWatcher`** — file watcher that polls STATE.md and the project directory for changes using `os.stat()`/`os.scandir()`, with gitignore-aware filtering and mtime-based caching
- **CLAUDE.md template** — `sago init` now generates a `CLAUDE.md` that teaches coding agents (Claude Code, Cursor, Aider, etc.) how to follow the plan: execute tasks in order, run verify commands, update STATE.md
- **Environment-aware planning** — planner injects Python version, OS, and platform into LLM context so it suggests compatible dependencies (no more pyflink on Python 3.13)
- **`<dependencies>` in PLAN.md** — planner generates a `<dependencies>` block listing third-party packages with version constraints; parser extracts them via `parse_dependencies()`
- **PEP 621 pyproject.toml guidance** — planner prompt includes a setuptools/PEP 621 template, preventing poetry/flit/hatch format generation
- **Plan summary display** — `sago plan` now shows a Rich table of phases/tasks and a dependencies panel after plan generation
- **Review gate in `sago run`** — plan is generated first, then displayed with a confirmation prompt before execution begins; skip with `--yes`/`-y`
- **ReviewerAgent** — new agent for reviewing generated code (post-execution quality gate)

### Fixed
- **CLAUDE.md template STATE.md format** — changed from `### Task [id]` (which the parser couldn't read) to `[✓] id: name` / `[✗] id: name` format matching the `parse_state_tasks()` regex
- **CLAUDE.md template phase transitions** — added instructions for the coding agent to write `## Phase Complete: [name]` to STATE.md and run `sago replan` between phases

### Changed
- **README rewritten** — reflects the new direction: sago plans, your coding agent builds. Includes concrete setup instructions for Claude Code, Cursor, Aider, and generic agents
- **CLAUDE.md (sago repo)** — updated to reflect planning-first architecture; executor marked as legacy

### Removed
- **SelfHealingAgent** — replaced by the executor's tool-use agent loop

## [0.1.2] - 2026-02-19

### Added

- **Native async LLM calls** — `achat_completion()` using `litellm.acompletion()` replaces `run_in_executor` workaround; streaming also async via `_astream_completion()`
- **Path traversal protection** — new `safe_resolve()` utility validates all LLM-generated file paths against project root; applied in executor, orchestrator, and project modules
- **Subprocess timeouts** — all `subprocess.run()` calls in git integration now have a 30-second timeout with `TimeoutExpired` handling
- **Verifier command blocklist** — blocks dangerous commands (`rm`, `dd`, `shutdown`, etc.) from running in verification steps
- **Concurrency controls** — `asyncio.TaskGroup` + `Semaphore` replace raw `asyncio.gather` for parallel task execution; configurable via `max_concurrent_tasks`
- **Shared LLM client** — single `LLMClient` instance reused across all agents instead of one per agent
- **File caching in executor** — `_file_cache` and `_tree_cache` avoid re-reading unchanged project files during execution
- **Web server event cap** — dashboard trace reader bounded to 5000 events per request
- **CI pipeline** — GitHub Actions workflow with Python 3.11/3.12 matrix, ruff, mypy, pytest
- **PEP 561 typing** — `py.typed` marker and `package-data` config for downstream type checking
- **Git integration tests** — 28 tests covering all `GitIntegration` methods including timeout handling
- **Path safety tests** — 7 tests for traversal attack prevention
- **Message validation** — `validate_messages()` called at the top of both sync and async LLM paths

### Changed

- **Interactive init by default** — `sago init` with no arguments now prompts for project name and description; AI generates PROJECT.md and REQUIREMENTS.md from the description. Pass `-y` to skip prompts. Removed the `-i`/`--interactive` flag
- **`AgentStatus` → `StrEnum`** — replaced `(str, Enum)` base classes with Python 3.11 `StrEnum`
- **Retry backoff** — switched from `wait_exponential` to `wait_exponential_jitter` for LLM retries
- **Cross-platform file locking** — `fcntl` import guarded by `sys.platform` check; gracefully skipped on Windows
- **Narrowed exception handlers** — bare `except Exception` replaced with specific types (`OSError`, `UnicodeDecodeError`, `json.JSONDecodeError`, etc.) across executor, orchestrator, and cache modules
- **Removed pytest from runtime deps** — moved to `[dev]` extras only

### Fixed

- **mypy strict compliance** — resolved all 17 type errors: `NoReturn` on `_raise_classified_error`, `None` guards on XML `.text`, Liskov-compliant compressor signatures, typed cache returns
- **Tracer span nesting** — fixed parent span tracking that was broken by returning a list copy instead of a reference
- **Examples** — `agent_workflow_example.py` uses `tempfile` instead of hardcoded paths; `compression_example.py` updated to current feature set

## [0.1.1] - 2026-02-19

### Added

- **IMPORTANT.md template** — `sago init` now generates IMPORTANT.md with project conventions; fed as context to PlannerAgent and ExecutorAgent

### Removed

- **Focus mode / blocker** — removed `--focus` flag, `sago block`, `sago unblock`, `sago block-list` commands, and the entire `blocker/` module

### Changed

- **Package metadata** — updated author, license (Apache-2.0), and description to "Spec-Aware Generation Orchestrator"

### Fixed

- **Path traversal** — tracer and demo now resolve paths before writing
- **Skylos gate** — split oversized functions, extracted complex try blocks into helpers
- **Dead parameters** — cleaned up unused args in demo trace builder

## [0.1.0] - 2026-02-18

### Added

- **CLI** — `sago init`, `sago plan`, `sago execute`, `sago run`, `sago status`, `sago trace` commands
- **Project scaffolding** — `sago init` creates PROJECT.md, REQUIREMENTS.md, IMPORTANT.md, PLAN.md, STATE.md templates
- **Prompt-based init** — `sago init --prompt "..."` generates PROJECT.md and REQUIREMENTS.md via LLM
- **Multi-agent pipeline** — PlannerAgent, ExecutorAgent, VerifierAgent coordinated by Orchestrator
- **Wave-based execution** — DependencyResolver groups tasks into dependency-free waves with circular dependency detection
- **Smart caching** — SHA256 hash of task definition + file contents; skips re-execution on cache hit (`--cache`, on by default)
- **Cost estimation** — `--dry-run` shows token usage and dollar cost per task before executing
- **Context compression** — `--compress` reduces LLM context via sliding window or LLMLingua strategies
- **Live observability dashboard** — `--trace` opens a real-time browser dashboard with Feed and Log tabs showing file reads, LLM calls, file writes, and verification results
- **Demo mode** — `sago trace --demo` streams a sample trace with no API key required
- **Multi-provider LLM support** — any LiteLLM-supported provider (OpenAI, Anthropic, Azure, Gemini, etc.)
- **Parallel execution** — opt-in via `ENABLE_PARALLEL_EXECUTION=true` for independent task waves
