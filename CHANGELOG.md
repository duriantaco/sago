# Changelog

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
- **Multi-agent pipeline** — PlannerAgent, ExecutorAgent, VerifierAgent, SelfHealingAgent coordinated by Orchestrator
- **Wave-based execution** — DependencyResolver groups tasks into dependency-free waves with circular dependency detection
- **Smart caching** — SHA256 hash of task definition + file contents; skips re-execution on cache hit (`--cache`, on by default)
- **Cost estimation** — `--dry-run` shows token usage and dollar cost per task before executing
- **Context compression** — `--compress` reduces LLM context via sliding window or LLMLingua strategies
- **Live observability dashboard** — `--trace` opens a real-time browser dashboard with Feed and Log tabs showing file reads, LLM calls, file writes, and verification results
- **Demo mode** — `sago trace --demo` streams a sample trace with no API key required
- **Multi-provider LLM support** — any LiteLLM-supported provider (OpenAI, Anthropic, Azure, Gemini, etc.)
- **Parallel execution** — opt-in via `ENABLE_PARALLEL_EXECUTION=true` for independent task waves
