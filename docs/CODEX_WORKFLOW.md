# Codex Workflow

Builder contract for Codex, aligned to the active control-plane roadmap.

## Source Of Truth

Read `docs/CONTROL_PLANE_ROADMAP.md` first in every session. It is the product source of truth for what `sago` is and is not:

- `sago` is a control plane for external builders, not an execution runtime.
- Codex is the first builder to optimize for, but the contract must stay builder-agnostic.
- Changes should strengthen plan quality, evidence, review, phase gates, state continuity, builder handoff, or governance visibility.

Use the roadmap for product intent, and use `PLAN.md`, `STATE.md`, and CLI `--json` output for current repo state. Do not treat chat history as authoritative. If the roadmap and repo state drift, surface the mismatch explicitly instead of inventing a hidden contract.

See `docs/CODEX_DOGFOOD.md` for the internal feature dogfood pass that validated this loop on `sago` itself.

Do not edit `STATE.md` directly when a CLI command exists for the mutation. Use `sago checkpoint`.

## Control-Plane Loop

Canonical loop:

```text
sago next --json -> build -> verify -> sago checkpoint -> sago status --json -> sago replan -> sago next --json
```

Execution rules:

1. Run `sago next --json`.
2. If `state == "task"`, execute only that task.
3. Build by editing the task's declared files plus any strictly necessary adjacent files.
4. Run the task's `verify` command yourself. Treat `verify_warnings` as real safety warnings.
5. If you captured verification output, write a receipt JSON file and attach it with `--receipt-file`.
6. Record the outcome with `sago checkpoint`.
7. Run `sago status --json` to confirm the persisted state, resume point, blockers, and recommendations.
8. Run `sago replan` when the task failed, a phase completed, requirements changed, or the plan is no longer the best path.
9. Return to `sago next --json`. Do not free-run past the control plane.

For Codex, prefer deterministic flags:

- `sago next --json`
- `sago checkpoint ... --json`
- `sago status --json`
- `sago replan --feedback "<reason>" --yes`

`sago replan` is not JSON-backed today. Treat it as the one non-JSON step in the loop and prefer `--feedback` plus `--yes` to avoid interactive prompts.

## `sago next --json` States

### `state == "task"`

Use this when work is actionable. Expected top-level fields:

- `success`
- `state`
- `phase`
- `task`
- `dependency_status`
- `agent_context`
- `verify_warnings`
- `resume_point`

Representative shape:

```json
{
  "success": true,
  "state": "task",
  "phase": "Phase 1: Foundation",
  "task": {
    "id": "1.2",
    "name": "Create Configuration Management",
    "files": ["src/sago/core/config.py"],
    "action": "Implement the task",
    "verify": "pytest tests/test_config.py::test_config_loads_env",
    "done": "Config loads from .env and provides type-safe settings",
    "phase_name": "Phase 1: Foundation",
    "depends_on": []
  },
  "dependency_status": [],
  "agent_context": {
    "present": true,
    "count": 1,
    "files": [
      {
        "path": "IMPORTANT.md",
        "kind": "project_rules",
        "description": "Non-negotiable project rules and constraints",
        "line_count": 4,
        "truncated": false
      }
    ],
    "errors": []
  },
  "verify_warnings": [],
  "resume_point": {
    "last_completed": "1.1: Initialize Python Project Structure",
    "next_task": "1.2: Create Configuration Management",
    "next_action": "Implement src/sago/core/config.py",
    "failure_reason": "None",
    "checkpoint": "sago-checkpoint-1.1"
  }
}
```

Codex should treat `task` as the only actionable unit. Use `agent_context.files` to discover repo-local instructions such as `IMPORTANT.md`, `AGENTS.md`, `SKILLS.md`, `CLAUDE.md`, or `.cursorrules`.

### `state == "blocked"`

Use this when no pending task is actionable. Expected fields today:

- `success`
- `state`
- `message`
- `failed_tasks`
- `reason` when the block is phase-gate related
- `phase` when the block is phase-gate related
- `blocking_findings` when the phase is blocked by critical review findings
- `agent_context`

Representative shape:

```json
{
  "success": true,
  "state": "blocked",
  "message": "Phase review required before continuing.",
  "reason": "phase_review_required",
  "phase": "Phase 1: Foundation",
  "failed_tasks": 0,
  "blocking_findings": [],
  "agent_context": {
    "present": false,
    "count": 0,
    "files": [],
    "errors": []
  }
}
```

`blocked` now covers two control-plane cases in addition to general "no actionable tasks":

- `reason == "phase_review_required"`: a completed phase has not been reviewed yet
- `reason == "phase_blocked"`: the stored phase review contains critical findings

When blocked, inspect `sago status --json` and then run `sago replan`.

### `state == "complete"`

Use this when every task is `done` or `skipped`. Expected fields:

- `success`
- `state`
- `message`
- `agent_context`

Representative shape:

```json
{
  "success": true,
  "state": "complete",
  "message": "All tasks complete!",
  "agent_context": {
    "present": false,
    "count": 0,
    "files": [],
    "errors": []
  }
}
```

`complete` means the current plan has no remaining actionable tasks. It does not override the roadmap; if the roadmap says more control-plane work is required, replan or update the plan explicitly.

## Practical Commands

Pick up work:

```bash
sago next --json
```

Verify a task using the task-provided command:

```bash
pytest tests/test_cli.py -q
```

Checkpoint a successful task with a concrete handoff:

```bash
sago checkpoint <task-id> \
  --status done \
  --notes "Implemented the task and ran verification successfully" \
  --next "<next-id>: <next task name>" \
  --next-action "<next concrete action>" \
  --decision "<durable decision>" \
  --json
```

Checkpoint a task with receipt-backed verification evidence:

```bash
sago checkpoint <task-id> \
  --status done \
  --notes "Verification passed" \
  --receipt-file .planning/tmp/receipt.json \
  --json
```

Receipt files are JSON. Useful fields include:

- `verify_command`
- `exit_code`
- `stdout`
- `stderr`
- `duration_ms`
- `files_changed`
- `builder`
- `git_head`

`sago` persists the raw receipt under `.planning/runtime/receipts/` and derives execution history in `.planning/runtime/execution_history.json`.

Expected checkpoint JSON fields:

- `success`
- `task_id`
- `task_name`
- `status`
- `notes`
- `next_task`
- `next_action`
- `decisions`
- `phase_name`
- `phase_completed`
- `phase_complete_name`
- `git_tag_created`
- `receipt`
- `evidence_summary`

`receipt` reports whether evidence was attached and, if so, the persisted receipt ID and runtime path.

Inspect persisted state after checkpoint:

```bash
sago status --json
```

Expected status JSON fields:

- `success`
- `project`
- `agent_context`
- `has_plan`
- `plan_error`
- `state`
- `task_summary`
- `evidence_summary`
- `memory_summary`
- `phases`
- `phase_gates`
- `recommendations`
- `blockers`
- `next_steps`

The nested `state` object currently contains `active_phase`, `current_task`, `task_states`, `decisions`, `blockers`, `resume_point`, and `phase_reviews`.

`phase_reviews` is a sanitized builder-facing map keyed by phase name. Each entry currently contains `phase_name`, `summary`, `gate_status`, `reviewed_at`, `reviewer`, `finding_count`, and `findings`. Raw review blobs are not part of the builder contract.

`phase_gates` contains the current gate state for completed phases, including `pending_review`, `approved`, or `blocked`, plus any blocking review findings.

`evidence_summary` gives a compact count of receipts, verified done tasks, done tasks still missing evidence, and repeated failures.

`memory_summary` is the current deterministic memory surface: decisions, blockers, and reviewed phases already stored in project state.

Status recommendations also surface receipt-backed execution issues, including repeated failures and done tasks that still lack evidence.

Replan deterministically when the loop says the plan needs to change:

```bash
sago replan --feedback "The task failed verification; adjust the remaining plan around the failure." --yes
```

## Codex Operating Notes

- Read the roadmap first, then trust CLI JSON over stale chat context.
- Do not skip `verify`, even for doc or refactor tasks, if the plan defines one.
- Do not mark a task done without a truthful `sago checkpoint`.
- Do not assume future roadmap fields are already implemented; follow the contract that is test-locked in `tests/test_cli_contracts.py`, `tests/test_builder_contracts.py`, and `tests/test_codex_flow.py`.
