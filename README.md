# Sago

<div align="center">
    <img src="assets/sago.png" alt="Sago - Turning your requirements into code" width="300">
    <h1>Sago: Turning your requirements into code</h1>
    <h3>A CLI that turns your requirements into working code. You describe what you want in markdown, sago generates a plan, writes the code, and verifies it works.</h3>
</div>

![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)
![Skylos](https://img.shields.io/badge/Skylos-PR%20Guard-2f80ed?style=flat&logo=github&logoColor=white)
![Dead Code Free](https://img.shields.io/badge/Dead_Code-Free-brightgreen?logo=moleculer&logoColor=white)


```
pip install -e .
```

```
sago init my-project        # scaffold PROJECT.md + REQUIREMENTS.md
# edit those files with what you want built
sago run                     # plan, execute, verify -- one command
```

Requires Python 3.11+.

---

## How it works

1. You write `PROJECT.md` (what the project is) and `REQUIREMENTS.md` (what it should do)
2. **Plan** -- sago calls an LLM to break your requirements into atomic tasks with verification commands
3. **Execute** -- each task gets its own LLM call that generates code and writes files
4. **Verify** -- each task's verification command runs automatically to confirm it works

The output is a `PLAN.md` with structured tasks, generated source files, and a `STATE.md` tracking what passed and what failed.

---

## Why sago over other LLM orchestrators

Most LLM coding orchestrators share a common design: spawn multiple agents in parallel, let them figure it out. This works for demos but falls apart on real projects. Here is where sago is different, and where it is honest about being on par.

### Where sago is objectively better

**You control the cost before you spend it.**
`sago run --dry-run` estimates token usage and dollar cost for every task before making a single LLM call. No other major orchestrator gives you a cost preview. You see exactly what a run will cost, broken down by phase, before you agree to it.

**Re-runs don't re-execute everything.**
Sago hashes each task's definition and the contents of its input files (SHA256). If nothing changed, the task is skipped entirely. Run `sago run` ten times on a half-finished project -- it only executes the new and modified tasks. Caching is on by default (`--no-cache` to disable).

**One LLM call per task, not N parallel agents.**
Sequential execution is the default. Each task gets exactly one LLM call to generate code, then one verification command. No agent spawning, no parallel rate limit exhaustion, no token cost explosion from agents duplicating work. You can opt into parallel execution (`ENABLE_PARALLEL_EXECUTION=true`) when your tasks are truly independent, but the default protects your API budget.

**Failures get classified and fixed, not just retried.**
`--auto-retry` doesn't blindly re-run failed tasks. It classifies the error (import error, syntax error, type error, name error, indentation error, test failure, or unknown), builds a targeted fix prompt for that error type, and makes a focused LLM call to fix it. The difference between "run it again and hope" and "here's what went wrong, fix this specific thing."

**It doesn't break when your editor updates.**
Sago is a standalone `pip install` CLI that calls LLM APIs directly. It has no dependency on VS Code, Cursor, Claude Code, or any other host tool. Editor updates, plugin version mismatches, and host CLI breaking changes don't affect your workflows.

### Where sago is on par

**Multi-provider LLM support.**
Sago uses LiteLLM, so it works with OpenAI, Anthropic, Azure, Gemini, and anything else LiteLLM supports. Switch providers by changing one environment variable. This is table stakes -- most serious orchestrators support multiple providers now.

**Language agnostic.**
Sago generates code via LLM calls and writes files. It doesn't parse your AST or depend on a specific language's toolchain. Python, TypeScript, Go, Rust, whatever -- if an LLM can write it, sago can orchestrate it. Other orchestrators that use LLMs for code generation are equally language-agnostic.

### Unique features (no direct comparison)

**Focus mode** (`--focus`) blocks distracting websites via `/etc/hosts` during workflow execution and auto-unblocks when the run finishes (success or failure). Not a coding feature -- a productivity feature. Configure the block list via `FOCUS_DOMAINS` or pass domains directly.

**Wave-based dependency resolution.** Tasks are analyzed for file dependencies and grouped into execution waves. Tasks in the same wave can run in parallel (if parallel mode is enabled); tasks with dependencies wait for their prerequisites. Circular dependencies are detected and rejected before execution starts.

---

## Commands

```bash
sago init [name]              # create project scaffold
sago plan                     # generate PLAN.md from requirements
sago execute                  # execute tasks from PLAN.md
sago run                      # plan + execute + verify in one step
sago status                   # show project progress
sago status -d                # detailed per-task breakdown

# Website blocker (standalone, requires sudo)
sudo sago block youtube.com reddit.com
sago block-list
sudo sago unblock
```

### Flags for `sago run`

| Flag | What it does |
|---|---|
| `--dry-run` | Estimate cost without executing |
| `--focus` | Block distracting sites during run |
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


## Development

```bash
pip install -e ".[dev]"       # install with dev dependencies

pytest                        # run all tests
pytest tests/test_parser.py -v              # single file
pytest tests/test_parser.py::test_name -v   # single test

ruff check src/               # lint
black src/ tests/             # format
mypy src/                     # type check (strict mode)
```

---

## Acknowledgements

This project was vibecoded with Claude Code.

Sago takes inspiration from:
- [GSD (Get Shit Done)](https://github.com/glittercowboy/get-shit-done) -- spec-driven development and sub-agent orchestration for Claude Code
- [Claude Flow](https://github.com/ruvnet/claude-flow) -- multi-agent orchestration platform with wave-based task coordination

---

## License

Apache 2.0. See [LICENSE](LICENSE).
