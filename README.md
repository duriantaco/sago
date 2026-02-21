# Sago

<div align="center">
    <img src="assets/sago.png" alt="Sago - AI project planning and orchestration" width="300">
    <h1>Sago: The project planner for AI coding agents</h1>
    <h3>You describe what you want in markdown. Sago generates a structured plan. Your coding agent (Claude Code, Cursor, Aider, etc.) builds it.</h3>
</div>

![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)
![Skylos](https://img.shields.io/badge/Skylos-PR%20Guard-2f80ed?style=flat&logo=github&logoColor=white)
![Dead Code Free](https://img.shields.io/badge/Dead_Code-Free-brightgreen?logo=moleculer&logoColor=white)

---

## What sago does

Sago is a **planning and orchestration tool**, not a coding agent. It turns your project idea into a structured, verified plan — then gets out of the way and lets a real coding agent do the building.

```
You → sago init → sago plan → coding agent builds Phase 1 → sago replan → coding agent builds Phase 2 → ...
```

**Why?** AI coding agents (Claude Code, Cursor, etc.) are excellent at writing code but bad at planning entire projects from scratch. They lose track of requirements, skip steps, and produce inconsistent architectures. Sago solves the planning problem so the coding agent can focus on what it's good at — writing code.

---

## Table of contents

- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Using with Claude Code](#using-with-claude-code)
- [Using with other agents](#using-with-other-agents)
- [Mission control](#mission-control)
- [Trace dashboard](#trace-dashboard)
- [Commands](#commands)
- [Configuration](#configuration)
- [Task format](#task-format)
- [Why sago](#why-sago)
- [Sago vs GSD](#sago-vs-gsd)
- [Development](#development)
- [Acknowledgements](#acknowledgements)
- [License](#license)

---

## Quick start

### 1. Install

```bash
pip install -e .
```

Requires Python 3.11+.

### 2. Set up your LLM provider

Create a `.env` file (or export the variables):

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_API_KEY=sk-your-key-here
```

Any [LiteLLM-supported provider](https://docs.litellm.ai/docs/providers) works — OpenAI, Anthropic, Azure, Gemini, etc. The LLM is used for **plan generation only**.

### 3. Create a project

```bash
sago init
```

Sago prompts for a project name and description. It generates the project scaffold:

```
my-project/
├── PROJECT.md          ← Vision, tech stack, architecture
├── REQUIREMENTS.md     ← What the project must do
├── PLAN.md             ← Atomic tasks with verify commands (after sago plan)
├── STATE.md            ← Progress log (updated as tasks complete)
├── CLAUDE.md           ← Instructions for the coding agent
├── IMPORTANT.md        ← Rules the coding agent must follow
└── .planning/          ← Runtime artifacts (cache, traces)
```

If you provide a description during init, the AI generates `PROJECT.md` and `REQUIREMENTS.md` for you. Otherwise, fill them in yourself.

### 4. Generate the plan

```bash
sago plan
```

Sago reads your `PROJECT.md` and `REQUIREMENTS.md`, detects your environment (Python version, OS, platform), and generates a `PLAN.md` with:

- Atomic tasks grouped into phases
- Dependency ordering
- Verification commands for each task
- A list of third-party packages needed

### 5. Hand off to your coding agent

Point your coding agent at the project and tell it to follow the plan:

**Claude Code:**
```bash
cd my-project
claude
# Claude Code reads CLAUDE.md automatically and follows the plan
```

**Cursor / Other agents:**
Open the project directory. The agent should read `PLAN.md` and execute tasks in order, running each `<verify>` command to confirm the task is done.

### 6. Watch your agent work

In a separate terminal, launch mission control:

```bash
sago watch
```

This opens a live dashboard in your browser that shows task completion, file activity, and phase progress — updated every second as your coding agent works through the plan.

### 7. Review between phases

After your coding agent finishes a phase, run the phase gate:

```bash
sago replan
```

This reviews the completed work, shows findings (warnings, suggestions), saves the review to STATE.md, and optionally lets you adjust the plan before the next phase. Just press Enter to skip replanning if the review looks good.

### 8. Track progress

```bash
sago status              # quick summary
sago status -d           # detailed per-task breakdown
```

---

## How it works

```
┌─────────────────────────────────────────────────────┐
│  1. SPEC                                            │
│     You write PROJECT.md + REQUIREMENTS.md          │
│     (or describe your idea and sago generates them) │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  2. PLAN (sago)                                     │
│     Sago calls an LLM to generate PLAN.md:          │
│     - Atomic tasks with verification commands       │
│     - Dependency-ordered phases                     │
│     - Environment-aware (Python version, OS)        │
│     - Lists required third-party packages           │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  3. BUILD (your coding agent)                       │
│     Claude Code / Cursor / Aider reads PLAN.md      │
│     and executes tasks one by one:                  │
│     - Follows <action> instructions                 │
│     - Runs <verify> commands                        │
│     - Updates STATE.md with progress                │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  4. REVIEW (sago replan)                            │
│     Between phases, reviews completed work:         │
│     - Runs ReviewerAgent on finished phases         │
│     - Shows warnings, suggestions, issues           │
│     - Saves review to STATE.md                      │
│     - Optionally updates the plan with feedback     │
└──────────────────────┬──────────────────────────────┘
                       ▼
              (repeat 3→4 for each phase)
                       ▼
┌─────────────────────────────────────────────────────┐
│  5. TRACK (sago)                                    │
│     sago status shows progress                      │
│     Dashboard shows real-time updates               │
└─────────────────────────────────────────────────────┘
```

Sago is the project manager. Your coding agent is the developer. The markdown files are the contract between them.

---

## Using with Claude Code

Sago generates a `CLAUDE.md` file during `sago init` that Claude Code reads automatically. It tells Claude Code how to follow the plan, execute tasks in order, and update STATE.md.

```bash
sago init my-project --prompt "A weather dashboard with FastAPI and PostgreSQL"
cd my-project
sago plan
claude
```

Claude Code picks up `CLAUDE.md` on startup and understands the task format. You can say something like:

> "Follow the plan in PLAN.md. Start with task 1.1 and work through each task in order."

Or let it read `CLAUDE.md` and figure it out — the instructions are already there.

---

## Using with Cursor

```bash
sago init my-project --prompt "A weather dashboard with FastAPI and PostgreSQL"
cd my-project
sago plan
```

Copy the sago workflow instructions into Cursor's rules file so the agent knows how to work:

```bash
cp CLAUDE.md .cursorrules
```

Then open the project in Cursor and use Agent mode. Tell it:

> "Read PLAN.md and execute each task in order. After each task, run the verify command and update STATE.md."

Cursor's agent will follow the plan the same way Claude Code does.

---

## Using with Aider

```bash
sago init my-project --prompt "A weather dashboard with FastAPI and PostgreSQL"
cd my-project
sago plan
```

Feed the plan and project context to Aider:

```bash
aider --read PLAN.md --read PROJECT.md --read REQUIREMENTS.md
```

Then tell it which task to work on:

> "Execute task 1.1 from PLAN.md. Create the files listed, follow the action instructions, then run the verify command."

Work through tasks one at a time since Aider works best with focused, single-task instructions.

---

## Using with any other agent

Sago's output is just markdown files. Any coding agent that can read files and run commands works. The agent needs to:

1. Read `PLAN.md` — the structured plan with phases and tasks
2. Read `PROJECT.md` — the project vision, tech stack, and architecture
3. Read `REQUIREMENTS.md` — what the project must do
4. If `PLAN.md` has a `<dependencies>` block, install those packages first
5. Execute tasks in order within each phase
6. Run each task's `<verify>` command — it must exit 0 before moving on
7. Update `STATE.md` after each task with pass/fail status

The `CLAUDE.md` file generated by `sago init` contains these instructions in a format most agents understand. Rename or copy it to whatever your agent expects (`.cursorrules`, `.github/copilot-instructions.md`, etc.).

---

## Mission control

While your coding agent builds the project, run mission control in a separate terminal:

```bash
sago watch                   # launch dashboard (auto-opens browser)
sago watch --port 8080       # use a specific port
sago watch --path ./my-app   # point to a different project
```

The dashboard shows:

- **Overall progress** — progress bar with task count and percentage
- **Phase tree** — every phase and task with live status icons (done, failed, pending)
- **File activity** — new and modified files detected in the project directory
- **Dependencies** — packages listed in PLAN.md
- **Per-phase progress bars** — at a glance, which phases are done

It polls STATE.md every second — as your coding agent marks tasks `[✓]` or `[✗]`, the dashboard updates automatically. No extra dependencies (stdlib HTTP server + `os.stat`).

## Trace dashboard

To view the planning trace after `sago plan`:

```bash
sago trace                   # opens dashboard for the last trace
sago trace --demo            # sample data, no API key needed
```

---

## Commands

```bash
sago init                            # interactive: prompts for name + description
sago init [name]                     # quick scaffold with templates
sago init [name] --prompt "desc"     # generate spec files from a prompt via LLM
sago init -y                         # non-interactive, all defaults
sago plan                            # generate PLAN.md from requirements
sago replan                          # phase gate: review completed work, optionally update plan
sago watch                           # launch mission control dashboard
sago watch --port 8080               # use a specific port
sago status                          # show project progress
sago status -d                       # detailed per-task breakdown
sago trace                           # open dashboard for the last trace
sago trace --demo                    # open dashboard with sample data
```

### Flags for `sago plan`

| Flag | What it does |
|---|---|
| `--force` / `-f` | Regenerate PLAN.md if it already exists |
| `--trace` | Open live dashboard during planning |

---

## Configuration

Create a `.env` file in your project directory:

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_API_KEY=your-key-here
LLM_TEMPERATURE=0.1
LLM_MAX_TOKENS=4096
LOG_LEVEL=INFO
```

Any [LiteLLM-supported provider](https://docs.litellm.ai/docs/providers) works. Set `LLM_MODEL` to the provider's model identifier (e.g., `claude-sonnet-4-5-20250929`, `gpt-4o`, `gemini/gemini-2.0-flash`).

---

## Task format

Tasks in `PLAN.md` use XML inside markdown:

```xml
<phases>
  <dependencies>
    <package>flask>=2.0</package>
    <package>sqlalchemy>=2.0</package>
  </dependencies>

  <review>
    Review instructions for post-phase code review...
  </review>

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

- **`<dependencies>`** — third-party packages needed, with version constraints
- **`<review>`** — instructions for reviewing each phase's output
- **`<task>`** — atomic unit of work with files, action, verification, and done criteria

The coding agent reads this format and executes tasks sequentially. Each task's `<verify>` command must exit 0 before moving on.

---

## Why sago

**The planning problem.** AI coding agents are great at writing code for a well-defined task. But ask them to build an entire project from a vague description and they lose track of requirements, skip steps, pick incompatible dependencies, and produce inconsistent architectures. The gap isn't in code generation — it's in project planning.

**Sago fills that gap.** It uses an LLM to generate a structured, verified plan with atomic tasks, dependency ordering, and environment-aware dependency suggestions. Then it hands off to whatever coding agent you prefer.

**Model-agnostic planning.** Sago uses [LiteLLM](https://docs.litellm.ai/docs/providers) for plan generation, so you're not locked into any provider. Use OpenAI, Anthropic, Azure, Gemini, Mistral — whatever gives you the best plans.

**Agent-agnostic execution.** Sago doesn't care what builds the code. Claude Code, Cursor, Aider, Copilot, a human — anything that can read markdown and follow instructions. Sago generates the plan; you choose the builder.

**Spec-first, always.** Every sago project has a reviewable spec (PROJECT.md, REQUIREMENTS.md) and a reviewable plan (PLAN.md) before any code is written. You see exactly what will be built and can adjust before spending time or tokens on execution.

---

## Sago vs GSD

[GSD (Get Shit Done)](https://github.com/glittercowboy/get-shit-done) is a great project that inspired sago. Both solve the same core problem — AI coding agents are bad at planning — but they take different approaches.

| | Sago | GSD |
|---|---|---|
| **What it is** | Standalone CLI tool (`pip install`) | Prompt system loaded into Claude Code |
| **Coding agent** | Any — Claude Code, Cursor, Aider, Copilot, a human | Claude Code only (uses its sub-agent spawning) |
| **Planning LLM** | Any LiteLLM provider (OpenAI, Anthropic, Gemini, etc.) | Claude (via Claude Code) |
| **Execution** | You hand off to your coding agent | GSD spawns executor agents in fresh contexts |
| **Context management** | Not sago's concern — your agent manages its own context | Core feature — fights "context rot" by spawning fresh 200k-token windows per task |
| **Phase transitions** | Explicit phase gate (`sago replan`) with code review and optional replan | Automatic wave-based execution with `/gsd:execute-phase` |
| **Research** | You write PROJECT.md + REQUIREMENTS.md (or generate from a prompt) | Spawns parallel researcher agents to investigate the domain |
| **Review** | `ReviewerAgent` runs between phases via `sago replan`, saves findings to STATE.md | `/gsd:verify-work` with interactive debug agents |

**When to use GSD:** You use Claude Code exclusively and want a fully automated pipeline — research, plan, execute, verify — all within Claude Code's sub-agent system. GSD's context rotation (fresh windows per task) is its killer feature for large projects.

**When to use sago:** You want to use different coding agents (or switch between them), want to use a non-Claude LLM for planning, or prefer an explicit human-in-the-loop workflow where you review the plan and gate phase transitions yourself. Sago is the project manager; you pick the developer.

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

## Acknowledgements

This project was vibecoded with Claude Code.

Sago takes inspiration from:
- [GSD (Get Shit Done)](https://github.com/glittercowboy/get-shit-done) — spec-driven development and sub-agent orchestration for Claude Code
- [Claude Flow](https://github.com/ruvnet/claude-flow) — multi-agent orchestration platform with wave-based task coordination

Dead code is kept in check by [Skylos](https://github.com/gregorylira/skylos).

---

## License

Apache 2.0. See [LICENSE](LICENSE).
