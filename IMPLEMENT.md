# Sago Architecture Evolution Plan

## Vision

Evolve Sago from text-driven plan management to a typed, execution-grounded planning and control plane for coding agents.

## Current State

Sago uses `@dataclass` models in `core/parser.py` (Task, Phase, Requirement, Milestone, ResumePoint) with XML embedded in markdown as the persistence format. Parsing is string-based with regex and `xml.etree`. State lives in `STATE.md` and `PLAN.md` as markdown files that serve as both human-readable and machine-readable — fragile for both purposes.

---

## Phase 1 — Typed Foundation

**Goal:** Add Pydantic models for Plan / Phase / Task / State / VerifyResult. Parse existing XML into typed models. Serialize typed models back to current format. Keep current UX and artifacts working.

### Task 1.1: Pydantic Plan + State + Execution Models

**Files:** `src/sago/models/__init__.py`, `src/sago/models/plan.py`, `src/sago/models/state.py`, `src/sago/models/execution.py`

Create Pydantic models replacing the dataclasses in `core/parser.py`:

- `Task`, `Phase`, `Dependency`, `ReviewPrompt`, `Plan` (with `all_tasks()`, `get_task()`, `task_ids()`, `dependency_graph()`)
- `TaskStatus` enum, `TaskState`, `ResumePoint`, `ProjectState` (with `completed_task_ids()`, `failed_task_ids()`, `pending_task_ids()`)
- `Requirement`, `Milestone`, `Requirements`, `Roadmap`
- `FailureCategory` enum, `VerifierResult`, `ExecutionRecord`, `ExecutionHistory` (with `failures_for_task()`, `repeated_failures()`)
- `classify_failure()` function — deterministic regex-based failure categorization

Add serialization: `to_json()` / `from_json()` on Plan, ProjectState, ExecutionHistory. Add `to_xml()` on Plan for backward compat. Add `to_dict()` on all models for backward compat with existing code.

**Verify:** `pytest tests/test_models.py -v`

### Task 1.2: Parser Migration

**Files:** `src/sago/core/parser.py`, `tests/test_parser.py`

Update `MarkdownParser` to return Pydantic models instead of dataclasses:
- `parse_xml_tasks()` → returns `list[Phase]` (Pydantic)
- `parse_requirements()` → returns `list[Requirement]` (Pydantic)
- `parse_roadmap()` → returns `list[Milestone]` (Pydantic)
- `parse_resume_point()` → returns `ResumePoint` (Pydantic)
- `parse_state_tasks()` → returns `list[dict[str, str]]` (unchanged interface)

Remove old dataclass definitions. Update tests.

**Verify:** `pytest tests/test_parser.py -v`

### Task 1.3: Agent + CLI Migration

**Files:** `src/sago/agents/planner.py`, `src/sago/agents/replanner.py`, `src/sago/agents/reviewer.py`, `src/sago/agents/orchestrator.py`, `src/sago/cli.py`

Update all consumers to import from `sago.models` instead of `sago.core.parser`. Mechanical migration — same field names, same attribute access.

**Verify:** `pytest -v` (full suite)

---

## Phase 2 — Validation and Execution Structure

**Goal:** Add semantic PlanValidator. Ship `sago lint-plan`. Add structured verifier results. Add regression + fixture-based test suite. Measure validation findings and verifier classification quality.

### Task 2.1: PlanValidator

**Files:** `src/sago/validation/__init__.py`, `src/sago/validation/validator.py`, `tests/test_validator.py`

`PlanValidator.validate(plan: Plan) -> ValidationResult` with:

**Errors:** duplicate task IDs, missing task IDs, invalid dependency refs, dependency cycles, empty action, empty files, illegal cross-phase backward deps.

**Warnings:** empty verify, missing done criteria, broad tasks (action > 2000 chars), duplicate files in same phase, task with > 8 files.

**Suggestions:** single-task phase, > 10 tasks in phase, over-specified deps.

### Task 2.2: Integrate Validation into Plan/Replan

**Files:** `src/sago/agents/planner.py`, `src/sago/agents/replanner.py`, `src/sago/agents/orchestrator.py`

After plan generation: parse → validate → block on errors (retry once with error feedback) → surface warnings in CLI.

### Task 2.3: `sago lint-plan` CLI Command

**Files:** `src/sago/cli.py`

`sago lint-plan [--path] [--strict] [--json]` — loads PLAN.md, validates, displays Rich-formatted results. `--strict` treats warnings as errors. `--json` outputs machine-readable. Exit code 0/1.

### Task 2.4: Wire Structured Execution into Replanner

**Files:** `src/sago/agents/replanner.py`

Include structured execution history in replan context — failure category, stderr snippet, attempt count per failed task.

### Success Criteria

- Run `sago lint-plan` against 5-10 real plans; false positive rate on warnings < 30%
- Run `classify_failure()` against fixture set of real stderr; correct categorization > 80%, `unknown` < 20%

---

## Phase 3 — Light State Intelligence

**Goal:** Add small deterministic recommendation engine. Start with 5-7 rules. Surface via CLI hints. Add basic approval gates for plan acceptance and risky replans.

### Task 3.1: Recommendation Engine

**Files:** `src/sago/recommendations/__init__.py`, `src/sago/recommendations/engine.py`, `tests/test_recommendations.py`

Rules (all deterministic, no LLM):
1. `warn_repeated_failure` — task failed >= 2 times
2. `suggest_replan` — > 30% of current phase tasks failed
3. `phase_complete` — all tasks in a phase done
4. `suggest_review` — phase complete, no review run
5. `warn_invalid_verify` — verify is empty or just `echo`/`true`
6. `warn_missing_tests` — task creates `.py` files but verify doesn't run pytest
7. `warn_scope_drift` — state references task IDs not in plan

### Task 3.2: Wire Recommendations into CLI

**Files:** `src/sago/cli.py`

Show recommendations after `sago status` and before `sago replan` feedback prompt. Concise, actionable, dismissible.

### Task 3.3: Approval Gates

**Files:** `src/sago/cli.py`, `src/sago/agents/orchestrator.py`

- `sago plan`: show validation results → prompt accept/reject → only write on acceptance
- `sago replan`: show diff + validation → prompt accept/reject → only persist on acceptance
- `--yes` skips prompts

---

## Phase 4 — Only If Real Pain Appears

Conditional. Only build if measured pain justifies it.

- **`.sago/` machine state** — only if markdown/XML state parsing becomes a reliability bottleneck
- **Patch-based replanning** — only if plan rewrite instability is measured and proven problematic
- **Markdown-native plan format** — only if XML actively hurts usability or adoption
- **Ecosystem interop (`AGENTS.md`)** — only when external conventions stabilize
