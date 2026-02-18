# Sago

<div align="center">
    <img src="assets/sago.png" alt="Sago - Turning your requirements into code" width="300">
    <h1>Sago: Turning your requirements into code</h1>
    <h3>A CLI that turns your requirements into working code. You describe what you want in markdown, sago generates a plan, writes the code, and verifies it works.</h3>
</div>

![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)
![Skylos](https://img.shields.io/badge/Skylos-PR%20Guard-2f80ed?style=flat&logo=github&logoColor=white)
![Dead Code Free](https://img.shields.io/badge/Dead_Code-Free-brightgreen?logo=moleculer&logoColor=white)

---

## Table of contents

- [Installation](#installation)
- [Step-by-step example](#step-by-step-example)
- [How it works](#how-it-works)
- [Live dashboard](#live-dashboard)
- [Why sago over other LLM orchestrators](#why-sago-over-other-llm-orchestrators)
- [Commands](#commands)
- [Configuration](#configuration)
- [Task format](#task-format)
- [Context compression](#context-compression)
- [Code quality](#code-quality)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Acknowledgements](#acknowledgements)
- [License](#license)

---

## Installation

```bash
pip install -e .
```

Requires Python 3.11+. Optional extras:

```bash
pip install -e ".[dev]"              # pytest, black, ruff, mypy
pip install -e ".[compression]"      # context compression (LLMLingua)
pip install -e ".[all]"              # everything
```

---

## Step-by-step example

This walks through building a weather dashboard from scratch — from install to watching it happen live in the dashboard.

### 1. Install sago

```bash
git clone https://github.com/yourusername/sago.git
cd sago
pip install -e .
```

### 2. Set up your LLM provider

Create a `.env` file in the sago directory (or export the variables):

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_API_KEY=sk-your-key-here
```

Any [LiteLLM-supported provider](https://docs.litellm.ai/docs/providers) works — OpenAI, Anthropic, Azure, Gemini, etc.

### 3. Create a project

**Option A** — generate from a prompt (LLM writes your spec):

```bash
sago init weather-app --prompt "A weather dashboard with FastAPI and PostgreSQL"
cd weather-app
```

**Option B** — write the spec yourself:

```bash
sago init weather-app
cd weather-app
```

Edit `PROJECT.md` with your vision and tech stack, and `REQUIREMENTS.md` with specific features:

```markdown
# REQUIREMENTS.md
* [ ] **REQ-1:** Display current weather for user's location
* [ ] **REQ-2:** Show 5-day forecast with min/max temperatures
* [ ] **REQ-3:** Allow searching by city name with autocomplete
```

Either way you end up with:

```
weather-app/
├── PROJECT.md          ← What you're building and why
├── REQUIREMENTS.md     ← What it should do (drives the plan)
├── PLAN.md             ← Atomic tasks with verify commands (generated)
├── STATE.md            ← Progress log (updated as tasks complete)
└── .planning/          ← Runtime artifacts (cache, traces)
```

### 4. Preview the cost

Before spending any tokens on execution:

```bash
sago run --dry-run
```

This estimates token usage and dollar cost for every task without making any LLM calls. Review, then proceed.

### 5. Run with the live dashboard

```bash
sago run --trace
```

This does everything — generates a plan, executes each task, verifies each one — and opens a live dashboard in your browser so you can watch it happen in real time.

The dashboard shows:
- **Feed tab** — each task as a card: file reads, LLM calls (click to see prompt/response), file writes (click to see content), verification pass/fail
- **Log tab** — every event in chronological order with timestamps, agent names, and color-coded types. Click any row to expand full details
- **Header** — live progress bar, total token count, elapsed time

### 6. Check results

After the run finishes:

```bash
sago status              # quick summary
sago status -d           # detailed per-task breakdown
```

Your generated source files are in the project directory. `STATE.md` shows what passed and what failed.

### 7. Resume or re-run

If some tasks failed, fix the spec and re-run — sago only re-executes changed or failed tasks (smart caching is on by default):

```bash
sago run --trace                  # skips completed tasks automatically
sago run --trace --auto-retry     # also auto-fix failed tasks via LLM
sago run --trace --force-plan     # regenerate the plan from scratch
```

### 8. Review a past trace

Open the dashboard for a completed run anytime:

```bash
sago trace                        # opens dashboard for the last run
sago trace --path ./weather-app   # specify project path
```

### Try the demo

Don't have an API key yet? See the dashboard with sample data:

```bash
sago trace --demo
```

This streams a realistic sample trace (a weather-app project with 3 tasks, including a failure + retry) so you can explore the Feed and Log tabs.

---

## How it works

1. **Spec** — you write `PROJECT.md` and `REQUIREMENTS.md` (or `--prompt` generates them)
2. **Plan** — sago calls an LLM to break your requirements into atomic tasks with verification commands
3. **Execute** — each task gets its own LLM call that generates code and writes files
4. **Verify** — each task's verification command runs automatically to confirm it works

The output is a `PLAN.md` with structured tasks, generated source files, and a `STATE.md` tracking what passed and what failed. Unlike tools that go straight from prompt to code, sago always produces a reviewable spec and plan — you see exactly what it intends to build before it writes a line of code.

---

## Live dashboard

Add `--trace` to any run and sago opens a real-time dashboard in your browser:

```bash
sago run --trace             # plan + execute + verify with live dashboard
sago execute --trace         # execute only, with dashboard
```

The dashboard has two tabs:

- **Feed** — task-centric view. Each task gets a card showing file reads, LLM calls (with expandable prompt/response), file writes (with expandable content), and verification results. Cards light up while active and show pass/fail when done.
- **Log** — chronological event table. Every event (LLM calls, file reads, file writes, verifications, errors) in order with timestamps, agent names, and color-coded types. Click any row to expand and see full details.

The header shows live progress (tasks completed / total), cumulative token usage, and elapsed time.

To view a past run's trace:

```bash
sago trace                   # opens dashboard for the last trace
sago trace --path ./my-project  # specify project path
sago trace --demo            # sample data, no API key needed
```

No extra dependencies — the dashboard uses Python's stdlib HTTP server and a self-contained HTML file.

---

## Why sago over other LLM orchestrators

Most LLM coding orchestrators share a common design: spawn multiple agents in parallel, let them figure it out. This works for demos but falls apart on real projects. Here is where sago is different, and where it is honest about being on par.

### Where sago is objectively better

**You control the cost before you spend it.**
`sago run --dry-run` estimates token usage and dollar cost for every task before making a single LLM call. No other major orchestrator gives you a cost preview. You see exactly what a run will cost, broken down by phase, before you agree to it.

**Re-runs don't re-execute everything.**
Sago hashes each task's definition and the contents of its input files (SHA256). If nothing changed, the task is skipped entirely. Run `sago run` ten times on a half-finished project — it only executes the new and modified tasks. Caching is on by default (`--no-cache` to disable).

**One LLM call per task, not N parallel agents.**
Sequential execution is the default. Each task gets exactly one LLM call to generate code, then one verification command. No agent spawning, no parallel rate limit exhaustion, no token cost explosion from agents duplicating work. You can opt into parallel execution (`ENABLE_PARALLEL_EXECUTION=true`) when your tasks are truly independent, but the default protects your API budget.

**Failures get classified and fixed, not just retried.**
`--auto-retry` doesn't blindly re-run failed tasks. It classifies the error (import error, syntax error, type error, name error, indentation error, test failure, or unknown), builds a targeted fix prompt for that error type, and makes a focused LLM call to fix it. The difference between "run it again and hope" and "here's what went wrong, fix this specific thing."

**It doesn't break when your editor updates.**
Sago is a standalone `pip install` CLI that calls LLM APIs directly. It has no dependency on VS Code, Cursor, Claude Code, or any other host tool. Editor updates, plugin version mismatches, and host CLI breaking changes don't affect your workflows.

### Where sago is on par

**Multi-provider LLM support.**
Sago uses LiteLLM, so it works with OpenAI, Anthropic, Azure, Gemini, and anything else LiteLLM supports. Switch providers by changing one environment variable. This is table stakes — most serious orchestrators support multiple providers now.

**Language agnostic.**
Sago generates code via LLM calls and writes files. It doesn't parse your AST or depend on a specific language's toolchain. Python, TypeScript, Go, Rust, whatever — if an LLM can write it, sago can orchestrate it. Other orchestrators that use LLMs for code generation are equally language-agnostic.

### Unique features (no direct comparison)

**Wave-based dependency resolution.** Tasks are analyzed for file dependencies and grouped into execution waves. Tasks in the same wave can run in parallel (if parallel mode is enabled); tasks with dependencies wait for their prerequisites. Circular dependencies are detected and rejected before execution starts.

---

## Commands

```bash
sago init [name]                     # create project scaffold with example templates
sago init [name] --prompt "desc"     # generate spec files from a prompt via LLM
sago plan                            # generate PLAN.md from requirements
sago execute                         # execute tasks from PLAN.md
sago run                             # plan + execute + verify in one step
sago status                          # show project progress
sago status -d                       # detailed per-task breakdown
sago trace                           # open dashboard for the last run's trace
sago trace --demo                    # open dashboard with sample data
```

### Flags for `sago run`

| Flag | What it does |
|---|---|
| `--dry-run` | Estimate cost without executing |
| `--trace` | Open live dashboard in browser |
| `--auto-retry` | Classify errors and attempt LLM-powered fixes |
| `--git-commit` | Auto-commit after each successful task |
| `--compress` | Compress LLM context for large codebases |
| `--no-cache` | Force re-execution of all tasks |
| `--no-verify` | Skip verification commands |
| `--continue-on-failure` | Don't stop on first failed task |
| `--force-plan` | Regenerate plan even if PLAN.md exists |

---

## Configuration

Create a `.env` file in your project directory:

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_API_KEY=your-key-here
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=4096

ENABLE_PARALLEL_EXECUTION=false
ENABLE_GIT_COMMITS=true
LOG_LEVEL=INFO
```

Any [LiteLLM-supported provider](https://docs.litellm.ai/docs/providers) works. Set `LLM_MODEL` to the provider's model identifier (e.g., `claude-sonnet-4-5-20250929`, `gpt-4o`, `gemini/gemini-2.0-flash`).

---

## Task format

Tasks in `PLAN.md` use XML inside markdown:

```xml
<phases>
  <phase name="Phase 1: Setup">
    <task id="1.1">
      <name>Create config module</name>
      <files>src/config.py</files>
      <action>Create configuration with pydantic settings...</action>
      <verify>python -c "import src.config"</verify>
      <done>Config module imports successfully</done>
    </task>
  </phase>
</phases>
```

Each task has a verification command that runs after code generation. If it exits 0, the task passed. If not, it failed (and `--auto-retry` can attempt a fix).

---

## Context compression

Enable `--compress` to reduce LLM token usage on large codebases. Sago supports two strategies:

- **Sliding window** — fast, trims older context. Good for chat-style interactions.
- **LLMLingua** — ML-based compression, 50-95% token reduction. Requires `pip install -e ".[compression]"`.

```bash
sago run --compress          # uses sliding window by default
```

Or use the Python API directly:

```python
from sago.utils.compression import ContextManager

manager = ContextManager(max_context_tokens=4000, compression_threshold=0.75)
result = manager.auto_compress(full_context)
print(f"Compressed from {result.original_tokens} to {result.compressed_tokens} tokens")
```

---

## Code quality

This codebase is kept clean with [Skylos](https://github.com/gregorylira/skylos), a dead code detection tool that runs as a PR guard. Skylos scans every pull request and flags unused functions, classes, imports, and variables before they get merged. The `Dead Code Free` badge at the top of this README means Skylos has verified there is no dead code in the current codebase.

```bash
skylos src/                  # run locally to check for dead code
```

---

## Development

```bash
pip install -e ".[dev]"       # install with dev dependencies

pytest                        # run all tests
pytest tests/test_parser.py -v              # single file
pytest tests/test_parser.py::test_name -v   # single test

ruff check src/               # lint
black src/ tests/             # format
mypy src/                     # type check (strict mode)
skylos src/                   # dead code detection
```

---

## Troubleshooting

**`ImportError: llmlingua not installed`** — Install compression extras: `pip install -e ".[compression]"`

**Context not compressing** — Text may be below the compression threshold. Lower it: set `COMPRESSION_THRESHOLD=0.5` in `.env` or pass it to `ContextManager`.

**`Trace file not found`** — You need to run with `--trace` first to generate a trace file, or use `sago trace --demo` for sample data.

---

## Acknowledgements

This project was vibecoded with Claude Code.

Sago takes inspiration from:
- [GSD (Get Shit Done)](https://github.com/glittercowboy/get-shit-done) — spec-driven development and sub-agent orchestration for Claude Code
- [Claude Flow](https://github.com/ruvnet/claude-flow) — multi-agent orchestration platform with wave-based task coordination

Dead code is kept in check by [Skylos](https://github.com/gregorylira/skylos).

---

## License

Apache 2.0. See [LICENSE](LICENSE).
