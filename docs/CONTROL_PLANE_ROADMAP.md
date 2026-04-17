# Sago Control-Plane Roadmap

This is the active roadmap for `sago`.

The goal is not to turn `sago` into another generic agent runtime. The goal is to make it the best builder-agnostic project control plane for AI coding agents, with Codex as the first executor to optimize for.

## Snapshot

- Date: 2026-04-16
- Primary executor target: Codex
- Secondary builders: Claude Code, Cursor, Aider, OpenHands
- Product category: planning, state, review, and phase governance for coding agents

## Ground Truth In Code Today

These files are the current product boundary and should anchor future work:

- Planning boundary: `README.md`, `docs/AGENT_SYSTEM_SUMMARY.md`
- Next-task contract: `src/sago/commands/next_cmd.py`
- Checkpoint and state mutation: `src/sago/commands/checkpoint_cmd.py`, `src/sago/state.py`
- Typed plan and execution models: `src/sago/models/plan.py`, `src/sago/models/execution.py`, `src/sago/models/state.py`
- Review and replanning: `src/sago/agents/reviewer.py`, `src/sago/agents/replanner.py`, `src/sago/commands/replan_cmd.py`
- Deterministic recommendations: `src/sago/recommendations/engine.py`
- Mission Control and watch server: `src/sago/web/server.py`, `src/sago/web/watcher.py`, `src/sago/web/mission_control.html`

## Product Thesis

`sago` wins if it becomes the durable project contract that survives:

- long-running work across days or weeks
- switching between builders
- failed tasks and replans
- human review before advancing phases
- chat/context resets

`sago` loses if it tries to compete head-on with agent runtimes on:

- browser and OS control
- autonomous execution loops
- built-in coding execution
- general-purpose agent memory
- broad skill marketplaces

## Market Wedge

The market is rapidly commoditizing planning, autonomous execution, and tool-local memory. The durable pain that remains is project governance across builder sessions and across builder products.

### Pain Map

| Pain | What the market is doing | What `sago` should do |
| --- | --- | --- |
| Planning is becoming table stakes | Native plan modes now exist inside major coding agents | Do not sell "plan generation" by itself |
| Execution runtimes are crowded | Major agents now ship long-running sandboxes and tool loops | Do not build a generic runtime |
| Context resets still break projects | Progress is trapped in chat history or tool-local state | Keep repo-local project contract and resumable state |
| "Done" is often unauditable | A task can be marked complete without evidence | Require receipts and verification artifacts |
| Cross-tool continuity is weak | Cursor/Claude/Codex/OpenHands each have their own context model | Be the neutral control plane above them |
| Phase gates are weak | Builders keep moving even when a phase should be reviewed | Make phase review and approval explicit |
| Memory is mostly personal, not project-level | Agent memory tends to be tool-local and broad | Keep only deterministic project memory tied to evidence |

### Positioning Sentence

`sago` should be positioned as:

> The project control plane for AI coding agents: durable spec, ordered work, evidence-backed checkpoints, and review gates across any builder.

## Hard Product Decisions

| Topic | Decision | Reason | Revisit Trigger |
| --- | --- | --- | --- |
| Generic agent runtime | No | Crowded category, high complexity, weak wedge | Only if builders become impossible to integrate with |
| Browser or OS control | No | Not part of the control-plane thesis | Never as core product |
| Knowledge graph database | No | High schema cost, low near-term user value | Only if file-based memory stops scaling |
| Embedding-based memory | Not now | Adds retrieval complexity before core state is trustworthy | Revisit after structured state and receipts ship |
| Deterministic project memory | Yes | Useful for decisions, blockers, failure patterns, verified commands | Build after state and phase gates |
| OpenClaw-style skill packaging | Maybe later | Useful only as thin reusable project recipes | Revisit after core governance is strong |
| Markdown as sole machine state | No | Brittle parsing is limiting | Replace with structured artifacts plus rendered markdown |
| Codex as first-class builder | Yes | Best fit for explicit files, JSON contracts, and deterministic flows | Start here |

## What To Borrow And What To Ignore

### Borrow From GenericAgent

- Principle: no execution, no memory
- Keep memory tied to verified outcomes, not model speculation
- Good memory categories: decisions, blockers, failure patterns, env facts, verified commands

### Do Not Borrow From GenericAgent

- direct tool runtime
- self-running autonomous loop
- broad "working memory" as hidden prompt state

### Borrow One Thing From OpenClaw Later

- Safe, bounded skill packaging and loading

That should only happen after the core roadmap below is complete. If it happens, it should be small, repo-local, and explicit. It should not become a gateway platform or skill marketplace.

## North-Star Outcomes

The roadmap is successful when all of the following are true:

1. A user can leave a project for three days, come back, run `sago status`, and know the true next step without reading old chats.
2. A task marked done has a receipt, a verify result, or an explicit reason it lacks evidence.
3. A completed phase cannot quietly roll into the next phase without review.
4. Replanning uses actual execution failures and accepted decisions, not only the latest prompt.
5. The same project can move between Codex, Claude Code, and Cursor without losing contract state.

## Metrics That Matter

- Receipt coverage: percent of done tasks with attached verification receipts
- Review coverage: percent of completed phases with stored review result
- Gate integrity: percent of phase transitions that passed through review
- Resume quality: percent of projects where `sago next --json` returns a valid actionable or explicit blocked state after interruption
- Replan usefulness: percent of repeated-failure tasks that receive targeted replan adjustments
- Verify quality: percent of tasks whose `verify` command is non-trivial and safe

## Operating Rules For Codex

Codex should follow these rules when implementing this roadmap:

1. Treat `sago` as a control-plane product, not an execution runtime.
2. Every change must strengthen one of these: plan quality, evidence, review, phase gates, state continuity, builder handoff, or governance visibility.
3. Prefer typed, deterministic state over prompt-only behavior.
4. Prefer additive `--json` contracts over brand-new commands unless a new command materially improves clarity.
5. Human-readable markdown should become a rendered view. Structured artifacts should become the canonical source of truth.
6. Any memory added to `sago` must be evidence-backed and scoped to the project, not the person or the conversation.
7. Each milestone must ship code, tests, and docs together.
8. If a proposed change pushes `sago` toward a generic runtime, stop and reject it.

## Target Architecture

The current markdown contract should remain visible, but machine state should move into `.planning/`.

### Canonical Artifact Layout

```text
.planning/
  runtime/
    project_state.json
    execution_history.json
    phase_reviews/
      phase-1.json
      phase-1.md
    receipts/
      receipt-<task>-<timestamp>.json
    memory/
      decisions.jsonl
      blockers.jsonl
      failure_patterns.jsonl
      env_facts.jsonl
      verified_commands.jsonl
```

### File Responsibilities

- `STATE.md`: rendered status summary for humans
- `.planning/runtime/project_state.json`: canonical task and phase state
- `.planning/runtime/execution_history.json`: all verify attempts and failure categories
- `.planning/runtime/phase_reviews/*.json`: structured review findings and phase gate decision
- `.planning/runtime/receipts/*.json`: raw task receipts from builders
- `.planning/runtime/memory/*.jsonl`: deterministic project memory extracted from evidence

### Canonical State Schema

```json
{
  "version": 1,
  "active_phase": "Phase 2: API",
  "current_task": "2.3",
  "tasks": {
    "2.3": {
      "status": "done",
      "note": "Added endpoint validation",
      "updated_at": "2026-04-16T10:15:00Z",
      "receipt_ids": ["receipt-2.3-20260416T101500Z"]
    }
  },
  "resume_point": {
    "last_completed": "2.3: Add validation",
    "next_task": "2.4: Add tests",
    "next_action": "Run pytest for API module",
    "failure_reason": "None",
    "checkpoint": "sago-checkpoint-2.3"
  },
  "phases": {
    "Phase 2: API": {
      "review_status": "approved",
      "completed_at": "2026-04-16T10:16:00Z",
      "review_file": ".planning/runtime/phase_reviews/phase-2.json"
    }
  }
}
```

### Canonical Receipt Schema

```json
{
  "receipt_id": "receipt-2.3-20260416T101500Z",
  "task_id": "2.3",
  "status": "done",
  "verify_command": "pytest tests/test_api.py -q",
  "exit_code": 0,
  "stdout": "...",
  "stderr": "",
  "duration_ms": 1432,
  "files_changed": [
    "src/api/routes.py",
    "tests/test_api.py"
  ],
  "recorded_at": "2026-04-16T10:15:00Z",
  "builder": "codex",
  "git_head": "abc1234"
}
```

### Canonical Memory Schema

```json
{
  "id": "decision-20260416-01",
  "kind": "decision",
  "summary": "Use SQLite in local development and PostgreSQL in production",
  "task_id": "1.4",
  "phase_name": "Phase 1: Foundation",
  "source": "checkpoint",
  "evidence_ids": ["receipt-1.4-20260416T083000Z"],
  "stability": "stable",
  "created_at": "2026-04-16T08:31:00Z"
}
```

## Execution Sequence

The implementation order matters. Do not start with memory. Do not start with a graph. Do not start with new runtimes.

1. Freeze scope and define the active contract
2. Make state trustworthy
3. Make checkpoints evidence-backed
4. Make phase gates real
5. Make Codex integration excellent
6. Add narrow project memory
7. Upgrade Mission Control and CI around the stronger core

## Phase 0 - Focus Freeze And Contract Cleanup

Goal: remove ambiguity about what `sago` is and is not.

### Tasks

- [x] `0.1` Publish the active roadmap
  - Create this roadmap and make it discoverable from `ROADMAP.md`
  - Keep `ROADMAP.md` but mark it as historical
  - Proof: `ROADMAP.md` now points to `docs/CONTROL_PLANE_ROADMAP.md` and marks the old file as historical.
- [x] `0.2` Tighten product language
  - Update `README.md` and `docs/AGENT_SYSTEM_SUMMARY.md`
  - Remove language that implies first-party execution or agent-runtime ambitions
  - Proof: `README.md` now links to the active roadmap and positions Codex as the primary executor target; `docs/AGENT_SYSTEM_SUMMARY.md` now documents the stable builder contract for `next --json`, `checkpoint --json`, and `status --json`.
- [x] `0.3` Write the builder contract doc
  - Add a Codex-first workflow doc
  - Document the exact loop: `sago next --json` -> build -> verify -> `sago checkpoint` -> `sago status --json` -> `sago replan`
  - Proof: `docs/CODEX_WORKFLOW.md` now documents the Codex-first control-plane loop, current `sago next --json` states, and expected JSON fields.
- [x] `0.4` Snapshot the JSON contract
  - Add tests that lock down current JSON for `next`, `status`, and `checkpoint`
  - Proof: `tests/test_cli_contracts.py` locks down task, blocked, and complete states for `next --json`, plus the JSON shapes for `status --json` and `checkpoint --json`.

### Files To Touch

- `README.md`
- `ROADMAP.md`
- `docs/AGENT_SYSTEM_SUMMARY.md`
- `docs/CONTROL_PLANE_ROADMAP.md`
- New builder workflow doc under `docs/`
- `tests/test_cli.py` or a new `tests/test_cli_contracts.py`

### Exit Criteria

- A new executor can understand `sago`'s product boundary without oral context
- Old roadmap content is clearly marked historical
- JSON contracts are test-covered before deeper changes begin

### Evidence

- 2026-04-16: `.venv/bin/pytest --no-cov tests/test_cli.py tests/test_cli_contracts.py` passed with `37 passed in 0.63s`.
- 2026-04-16: the same focused slice without `--no-cov` passed functionally but failed the repo-wide coverage gate because total coverage for the partial run was `47.05%`, below the configured `80%` fail-under. The contract tests themselves passed.

## Phase 1 - Canonical Structured State

Goal: stop treating markdown as the only machine-readable state store.

### Why This Comes First

Current state is markdown-centric inside `src/sago/state.py`. That is useful for humans but too brittle for long-term tracking, receipts, memory extraction, and phase gates.

### Tasks

- [x] `1.1` Introduce a structured persistence layer
  - Add a new package such as `src/sago/persistence/`
  - Move canonical reads and writes for project state into typed JSON-backed stores
  - Proof: `src/sago/persistence/project_state.py` now defines the canonical JSON-backed state store and markdown migration/rendering logic.
- [x] `1.2` Keep backward compatibility
  - On existing projects, read `STATE.md` and materialize `project_state.json`
  - Do not break existing repos that only have markdown state
  - Proof: legacy `STATE.md` is migrated into `.planning/runtime/project_state.json`, and newer `STATE.md` edits are re-materialized back into canonical JSON when they are newer than the structured store.
- [x] `1.3` Render `STATE.md` from structured state
  - Keep `STATE.md` as a human-facing summary
  - Remove markdown from the role of single source of truth
  - Proof: `StateManager` now saves canonical JSON and renders `STATE.md` from it on every mutation.
- [x] `1.4` Switch command readers to structured state
  - Update `next`, `status`, `replan`, `watch`, and recommendations to prefer the structured store
  - Proof: `src/sago/state.py`, `src/sago/web/watcher.py`, and `src/sago/commands/replan_cmd.py` now read through the structured state path instead of relying on raw markdown parsing at the call site.
- [x] `1.5` Add migration tests
  - Cover fresh project, legacy project, and mixed-mode project behavior
  - Proof: `tests/test_state_migration.py` covers legacy migration, checkpoint dual-write behavior, JSON-only recovery, phase metadata persistence, and watcher reads without `STATE.md`.

### Suggested File Areas

- `src/sago/state.py`
- `src/sago/models/state.py`
- new `src/sago/persistence/`
- `src/sago/commands/next_cmd.py`
- `src/sago/commands/status_cmd.py`
- `src/sago/commands/replan_cmd.py`
- `src/sago/web/watcher.py`
- `tests/test_state.py`
- new `tests/test_state_migration.py`

### Acceptance Criteria

- `sago checkpoint` writes structured state and updates `STATE.md`
- `sago status --json` and `sago next --json` work without parsing markdown for primary state
- Legacy state files continue to load correctly
- No regression in current CLI behavior

### Evidence

- 2026-04-17: `.venv/bin/pytest --no-cov tests/test_state.py tests/test_state_migration.py tests/test_watcher.py tests/test_cli.py tests/test_cli_contracts.py tests/test_dashboard_server.py` passed with `100 passed in 1.18s`.
- 2026-04-17: `.venv/bin/pytest --no-cov tests/test_replanner.py tests/test_integration.py` passed with `24 passed in 0.61s`.

## Phase 2 - Evidence-Backed Checkpoints

Goal: a task marked done or failed should be backed by real execution evidence whenever available.

### Why This Matters

Without receipts, `sago` cannot distinguish "task completed" from "task claimed completed". Evidence is the foundation for stronger recommendations, review, and trust.

### Tasks

- [x] `2.1` Define a receipt format
  - Add a typed receipt model
  - Support task ID, builder, verify command, exit code, duration, stdout, stderr, changed files, git head
  - Proof: `src/sago/models/execution.py` now defines `CheckpointReceipt` with normalized task/status validation and execution-record conversion.
- [x] `2.2` Extend `sago checkpoint`
  - Add `--receipt-file` support
  - Preserve the current lightweight flow when no receipt exists
  - Proof: `src/sago/commands/checkpoint_cmd.py` now accepts `--receipt-file` and persists receipt-backed execution data without changing the existing checkpoint JSON response shape.
- [x] `2.3` Persist execution history canonically
  - Save receipts into `.planning/runtime/receipts/`
  - Update `.planning/runtime/execution_history.json`
  - Proof: `src/sago/persistence/execution_history.py` now stores raw receipt JSON and appends derived execution records to `.planning/runtime/execution_history.json`.
- [x] `2.4` Classify failures deterministically
  - Reuse and extend `src/sago/models/execution.py`
  - Make repeated-failure logic operate on real receipts
  - Proof: receipt-backed execution records now carry deterministic failure categories, and repeated-failure recommendations are driven from persisted execution history.
- [x] `2.5` Surface evidence gaps
  - Warn when a task is marked done without a receipt
  - Expose receipt coverage in `status --json` and Mission Control
  - Proof: `src/sago/recommendations/engine.py` and `src/sago/commands/status_cmd.py` now surface repeated failures and missing evidence through status recommendations, and `src/sago/web/watcher.py` plus `src/sago/web/mission_control.html` now expose and render receipt coverage in Mission Control.

### Suggested File Areas

- `src/sago/models/execution.py`
- `src/sago/commands/checkpoint_cmd.py`
- `src/sago/recommendations/engine.py`
- `src/sago/web/watcher.py`
- `src/sago/commands/status_cmd.py`
- new `tests/test_checkpoint_receipts.py`
- `tests/test_recommendations.py`

### Acceptance Criteria

- A builder can attach a receipt file to a checkpoint
- `sago` stores and exposes verify evidence for each attempt
- Repeated failures are derived from execution history, not only status markers
- A done task without evidence is visible as a warning, not silently accepted

### Evidence

- 2026-04-17: `.venv/bin/pytest --no-cov tests/test_checkpoint_receipts.py tests/test_recommendations.py tests/test_cli.py tests/test_cli_contracts.py` passed with `62 passed in 0.88s`.
- 2026-04-17: `.venv/bin/pytest --no-cov tests/test_models.py tests/test_checkpoint_receipts.py tests/test_recommendations.py` passed with `63 passed in 1.63s`.
- 2026-04-17: `.venv/bin/pytest --no-cov tests/test_watcher.py tests/test_dashboard_server.py tests/test_checkpoint_receipts.py` passed with `30 passed in 0.76s`.

## Phase 3 - Real Phase Gates

Goal: make phase review an actual gate, not a polite suggestion.

### Why This Matters

The control-plane thesis depends on preventing silent drift between phases. If builders can skip review and continue anyway, `sago` becomes advisory instead of authoritative.

### Tasks

- [x] `3.1` Add a structured phase review model
  - Introduce `PhaseReview`, `ReviewFinding`, and explicit severity
  - Persist both structured JSON and rendered markdown
  - Proof: `src/sago/models/state.py` now defines `PhaseReview`, `ReviewFinding`, `ReviewSeverity`, and `PhaseGateStatus`, and `src/sago/persistence/project_state.py` persists reviews into canonical state while rendering them back into `STATE.md`.
- [x] `3.2` Upgrade the reviewer contract
  - Make `ReviewerAgent` return machine-readable findings plus human summary
  - Keep file and line references first-class
  - Proof: `src/sago/agents/reviewer.py` now requests JSON-only review output, parses structured findings, and returns a rendered summary plus machine-readable review metadata.
- [x] `3.3` Add phase gate states
  - Supported states: `pending_review`, `approved`, `blocked`
  - Derive gate state from completed tasks plus review findings
  - Proof: `src/sago/commands/__init__.py` now derives explicit per-phase gate states, `src/sago/commands/status_cmd.py` surfaces them in `status --json`, and `src/sago/web/watcher.py` plus `src/sago/web/mission_control.html` surface them in Mission Control.
- [x] `3.4` Block `sago next` on pending review
  - If the current phase is complete but not reviewed, `next --json` should return a blocked state with reason `phase_review_required`
  - If a review has blocking findings, return `phase_blocked`
  - Proof: `src/sago/commands/next_cmd.py` now blocks progression on `phase_review_required` and `phase_blocked`, including critical finding details in the blocked payload.
- [x] `3.5` Make `sago replan` consume stored reviews
  - Review first
  - Replan second
  - Preserve done-task immutability
  - Proof: `src/sago/commands/replan_cmd.py` now reuses stored reviews, runs missing reviews before replanning, and persists structured review results back into canonical state.

### Suggested File Areas

- `src/sago/agents/reviewer.py`
- `src/sago/commands/replan_cmd.py`
- `src/sago/commands/next_cmd.py`
- `src/sago/models/`
- `src/sago/state.py` or new persistence layer modules
- new `tests/test_phase_gate.py`
- `tests/test_reviewer.py`
- `tests/test_integration.py`

### Acceptance Criteria

- Finishing the last task in a phase does not automatically unlock the next phase
- `sago next --json` can explain exactly why progress is blocked
- Structured review findings are visible in `status --json` and Mission Control
- Replanning can rely on persisted review data instead of a one-off screen output

### Evidence

- 2026-04-17: `.venv/bin/pytest --no-cov tests/test_cli_contracts.py tests/test_phase_gate.py tests/test_reviewer.py` passed with `31 passed in 0.51s`.
- 2026-04-17: `.venv/bin/pytest --no-cov tests/test_cli.py tests/test_state.py tests/test_state_migration.py tests/test_replanner.py` passed with `88 passed in 0.95s`.
- 2026-04-17: `.venv/bin/pytest --no-cov tests/test_watcher.py tests/test_dashboard_server.py tests/test_recommendations.py tests/test_checkpoint_receipts.py` passed with `52 passed in 1.70s`.

## Phase 4 - Codex-First Builder Integration

Goal: make Codex the best-supported executor without making `sago` executor-specific.

### Why This Matters

Codex is a strong fit for `sago` because it works well with explicit file contracts, JSON outputs, and deterministic command loops. If Codex integration is clean, every other builder integration becomes easier.

### Tasks

- [x] `4.1` Publish a Codex execution runbook
  - Give exact instructions for task pickup, verify, receipts, checkpoints, and replan loops
  - Make no assumptions about hidden daemon state
  - Proof: `docs/CODEX_WORKFLOW.md` now documents the current builder contract, and `docs/CODEX_DOGFOOD.md` records the dogfood loop used on this repo.
- [x] `4.2` Stabilize the JSON builder contract
  - Treat `next --json`, `status --json`, and `checkpoint --json` as stable interfaces
  - Add fixture-based schema tests
  - Proof: `tests/test_cli_contracts.py` plus `tests/test_builder_contracts.py` now lock down the builder-facing JSON contract, including non-empty `phase_gates`, sanitized `phase_reviews`, and attached `checkpoint.receipt` metadata.
- [x] `4.3` Dogfood `sago` with Codex
  - Use the control-plane flow on a real internal feature
  - Validate interruption, resume, failure, review, and replan
  - Proof: `tests/test_codex_flow.py` now exercises the Codex loop across failure, resume, review, replan, and continuation on a real internal feature flow, and `docs/CODEX_DOGFOOD.md` now includes an abridged recorded transcript of that loop.
- [x] `4.4` Improve builder-facing payloads
  - Include gate reason, evidence summary, and memory summary in JSON outputs where useful
  - Keep outputs concise and deterministic
  - Proof: `src/sago/commands/status_cmd.py` now exposes `evidence_summary` and `memory_summary`, and `src/sago/commands/checkpoint_cmd.py` now returns deterministic receipt metadata plus post-checkpoint evidence summary.

### Suggested File Areas

- `docs/`
- `src/sago/commands/next_cmd.py`
- `src/sago/commands/status_cmd.py`
- `src/sago/commands/checkpoint_cmd.py`
- `tests/test_cli.py`
- new `tests/test_builder_contracts.py`
- new `tests/test_codex_flow.py`

### Acceptance Criteria

- A Codex executor can use only repo files and CLI outputs to drive a feature from plan to phase review
- JSON outputs are stable enough to treat as a real builder API
- Dogfooding reveals no dependency on chat history

### Evidence

- 2026-04-17: `.venv/bin/pytest --no-cov tests/test_builder_contracts.py tests/test_codex_flow.py tests/test_checkpoint_receipts.py tests/test_phase_gate.py tests/test_state_migration.py tests/test_reviewer.py` passed with `46 passed in 0.44s`.
- 2026-04-17: `.venv/bin/pytest --no-cov tests/test_cli_contracts.py tests/test_cli.py tests/test_recommendations.py tests/test_watcher.py tests/test_dashboard_server.py tests/test_state.py` passed with `121 passed in 1.01s`.

## Phase 5 - Narrow Deterministic Project Memory

Goal: add project memory that improves planning and replanning without turning `sago` into a memory-heavy agent.

### Hard Rules

- No conversational memory
- No persona memory
- No hidden working memory
- No knowledge graph database
- No embeddings as a requirement for V1
- Memory must come from evidence-backed events

### Allowed Memory Categories

- decisions
- blockers
- failure patterns
- env facts
- verified commands that worked

### Retrieval Rules

Use simple heuristics first:

1. Match by exact task ID when present
2. Match by phase name
3. Match by dependency neighborhood
4. Prefer stable items over ephemeral items
5. Prefer newer items when scores tie
6. Hard-cap prompt injection size

### Tasks

- [ ] `5.1` Add typed memory entries and stores
  - Use JSONL under `.planning/runtime/memory/`
- [ ] `5.2` Extract memory from checkpoints and reviews
  - Decisions from checkpoint flags
  - Blockers from failed or blocked states
  - Failure patterns from repeated receipt failures
  - Env facts from doctor/environment detection
  - Verified commands from successful receipts
- [ ] `5.3` Inject memory into planner, replanner, and reviewer prompts
  - Keep prompt additions scoped and ranked
- [ ] `5.4` Surface memory summaries
  - Add top decisions and blockers to `status --json`
  - Optionally show memory-backed hints in `next --json`

### Suggested File Areas

- new `src/sago/memory/`
- `src/sago/agents/planner.py`
- `src/sago/agents/replanner.py`
- `src/sago/agents/reviewer.py`
- `src/sago/commands/status_cmd.py`
- `tests/test_planner.py`
- `tests/test_replanner.py`
- new `tests/test_memory.py`

### Acceptance Criteria

- Replanner can use actual prior failures and decisions when updating plans
- Memory entries are traceable to evidence IDs
- No embeddings, graph database, or opaque self-mutating memory is required

## Phase 6 - Mission Control And CI As Governance Surfaces

Goal: make the UI and automation reflect real governance state, not just cosmetic activity.

### Tasks

- [ ] `6.1` Upgrade Mission Control metrics
  - Show gate status, review findings count, receipt coverage, repeated failures, and active blockers
- [ ] `6.2` Reduce decorative-only signals
  - Any prominent UI element should map to canonical state or trace data
- [ ] `6.3` Add CI policy checks
  - No completed phase without review
  - No blocked phase transition
  - No obviously invalid verify commands
  - No done task without explicit evidence state
- [ ] `6.4` Publish merge-time workflow examples
  - GitHub Actions or other CI examples using stable JSON outputs

### Suggested File Areas

- `src/sago/web/mission_control.html`
- `src/sago/web/watcher.py`
- `src/sago/web/server.py`
- `src/sago/commands/status_cmd.py`
- `tests/test_dashboard_server.py`
- `tests/test_watcher.py`
- new CI workflow examples under `.github/workflows/`

### Acceptance Criteria

- Mission Control can answer these questions without guesswork:
  - What is the next task?
  - Why is work blocked?
  - Which phases are approved?
  - Which done tasks have evidence?
  - Which tasks are failing repeatedly?
- CI can fail a change when phase governance is violated

## What Not To Build In The Next 6 Months

- no first-party execution runtime
- no browser automation
- no OS/device control
- no autonomous scheduler
- no subagent platform as core product
- no general-purpose memory system
- no graph database
- no skill marketplace
- no "self-improving" prompt memory

## Risks And Mitigations

| Risk | Why It Matters | Mitigation |
| --- | --- | --- |
| Migration away from markdown breaks projects | Current repos rely on `STATE.md` | Keep markdown rendering, add migration tests, preserve compatibility |
| Receipt format becomes too heavy for builders | Builders may skip it | Make receipts optional at first, but visible when missing |
| Reviewer output stays noisy | Gates become frustrating | Force structured findings, severity, and clear blocked criteria |
| Memory scope expands too far | Product loses focus | Keep only five memory categories and require evidence linkage |
| Dashboard outpaces reality | UI loses credibility | Show only canonical state and trace-backed signals |
| Codex integration becomes too custom | Product loses neutrality | Keep everything builder-agnostic beneath the docs and examples |

## Suggested Test Additions

- `tests/test_cli_contracts.py`
- `tests/test_state_migration.py`
- `tests/test_checkpoint_receipts.py`
- `tests/test_phase_gate.py`
- `tests/test_builder_contracts.py`
- `tests/test_codex_flow.py`
- `tests/test_memory.py`

## Suggested Order Of Work For The Next 8-12 Weeks

1. Finish Phase 0 immediately
2. Build Phase 1 before any memory or dashboard work
3. Build Phase 2 before tightening recommendations
4. Build Phase 3 before claiming `sago` has real governance
5. Build Phase 4 and dogfood with Codex
6. Build Phase 5 only after evidence-backed state exists
7. Build Phase 6 last, once the underlying state is trustworthy

## Executor Tracking Protocol

Codex should update this roadmap as work lands.

### Rule For Marking A Task Complete

Only mark a checkbox complete when all of these are true:

- code merged or committed locally
- tests added or updated
- docs updated if behavior changed
- command output or UI behavior verified

### Per-Task Execution Loop

1. Read the relevant source files named in this roadmap
2. Implement the smallest coherent change
3. Add or update targeted tests
4. Run the relevant test subset
5. Update the checkbox and any acceptance notes
6. Move to the next task only if the current task is truly complete

## Source Snapshot Used For Market Reasoning

The wedge and market decisions above were informed by a 2026-04-16 snapshot of:

- Claude Code docs on workflows, planning, permissions, and memory
- Cursor docs and changelogs on plan mode, memories, indexing, and long-running agents
- OpenHands docs on planning and skills
- OpenAI docs and product pages for Codex and Agents
- code inspection of `GenericAgent` and `OpenClaw`

Those sources support the core conclusion: planning and runtime features are being absorbed into the builders, while durable project governance remains under-served.
