# Sago Agent Architecture

Sago uses a small set of LLM-backed helper agents for planning and review.

The product boundary is intentional:
- Sago defines and updates the work
- Your coding agent or a human executes the work
- Sago tracks state, reviews completed phases, and exposes observability

Sago does **not** execute project tasks or apply task-level code changes itself.

## Current Components

### `BaseAgent`

Shared infrastructure for planner, replanner, and reviewer agents:
- LiteLLM integration
- structured `AgentResult`
- logging and trace emission

### `PlannerAgent`

Generates `PLAN.md` from:
- `PROJECT.md`
- `REQUIREMENTS.md`
- optional project context like `STATE.md`, repo map, and environment details

Responsibilities:
- produce atomic XML tasks
- include verification commands
- validate structure and semantics
- save the normalized `PLAN.md`

### `ReplannerAgent`

Updates `PLAN.md` without regenerating the entire project plan from scratch.

Responsibilities:
- preserve completed work
- incorporate user feedback
- use review findings and project context
- validate and rewrite the full plan

### `ReviewerAgent`

Reviews completed phases during `sago replan`.

Responsibilities:
- inspect files created by completed tasks
- compare the output against the review prompt
- report actionable findings with severity and references where possible

### `PlanningWorkflow`

Coordinates plan, review, and replan workflows for the CLI.

Notes:
- implemented in `src/sago/agents/orchestrator.py`
- legacy import alias: `Orchestrator`
- does not execute project tasks

## External Execution Contract

The builder is external to Sago:
- Claude Code
- Codex
- Cursor
- Aider
- Copilot
- a human developer

The intended command contract is:
1. `sago plan`
2. builder runs `sago next`
3. builder completes the task and runs `sago checkpoint`
4. repeat until a phase completes
5. `sago replan` reviews the completed phase and updates the plan if needed

## Why This Boundary Exists

Execution agents already specialize in:
- editing files
- navigating repositories
- running tools and tests
- iterating on failures

Sago is stronger as the planning and governance layer:
- spec-first project setup
- structured task planning
- state tracking
- review gates
- mission control and diagnostics

That separation keeps the product easier to understand and easier to trust.
