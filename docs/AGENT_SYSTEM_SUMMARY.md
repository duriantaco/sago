# Sago Architecture Summary

## Product Boundary

Sago is a planning and control-plane CLI for coding agents.

It is responsible for:
- turning project specs into a structured plan
- exposing the next task to the builder
- recording progress in `STATE.md`
- reviewing completed phases
- updating the plan when requirements change
- showing diagnostics and mission-control state

It is **not** responsible for:
- writing product code task by task
- applying patches to the target project as a first-party executor
- owning the execution loop of the coding agent

## Active Workflow

1. `sago init` or `sago import`
2. `sago plan`
3. external builder executes tasks using `sago next`
4. external builder records progress using `sago checkpoint`
5. `sago replan` reviews completed phases and updates the plan when needed
6. `sago status`, `sago watch`, and `sago doctor` provide visibility and validation

## Builder Contract

The builder-facing contract should remain stable and explicit.

- `sago next --json`
  - returns one of `task`, `complete`, or `blocked`
  - is the task-pickup surface for external builders
- `sago checkpoint --json`
  - records task outcome and returns the canonical checkpoint result
- `sago status --json`
  - exposes current project state, recommendations, blockers, and phase progress

Codex is the first executor target to optimize for, but these interfaces must stay builder-agnostic.

## Active Internal Components

### `PlannerAgent`

Generates the initial `PLAN.md` and validates it.

### `ReplannerAgent`

Updates the plan while preserving completed work.

### `ReviewerAgent`

Reviews completed phases during `sago replan`.

### `PlanningWorkflow`

Coordinates the CLI-facing planning, review, and replanning workflows.
The historical name `Orchestrator` remains as a compatibility alias.

## Cleanup Direction

The repository previously contained executor-oriented terminology and design assumptions.
The current direction is intentionally narrower:
- keep planning and review first-party
- keep execution external
- keep the CLI and builder contract stable for any builder

That gives Sago a clearer position: project manager and phase gate for coding agents.

The active implementation plan for this direction lives in `docs/CONTROL_PLANE_ROADMAP.md`.
