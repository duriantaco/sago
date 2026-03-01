# CLAUDE.md

This project is managed by [sago](https://github.com/yourusername/sago). Follow the instructions below when working on this codebase.

## Workflow

You are the coding agent for this project. Sago has generated a structured plan in `PLAN.md` — your job is to execute it task by task.

### How to work through the plan

1. **Read `PLAN.md`** to understand the full plan — phases, tasks, dependencies
2. **Read `PROJECT.md`** for the project vision, tech stack, and architecture
3. **Read `REQUIREMENTS.md`** for what the project must do
4. **Execute tasks in order** — complete each task's `<action>`, then run its `<verify>` command
5. **After each task**, update `STATE.md` with the result (pass/fail, notes)
6. **If a verify command fails**, fix the issue before moving to the next task

### Task format

Each task in `PLAN.md` looks like this:

```xml
<task id="1.1">
  <name>What to do</name>
  <files>files/to/create/or/modify.py</files>
  <action>Detailed instructions</action>
  <verify>command that exits 0 on success</verify>
  <done>What "done" looks like</done>
</task>
<task id="1.2" depends_on="1.1">
  <name>Depends on 1.1</name>
  <files>files/to/create.py</files>
  <action>Detailed instructions</action>
  <verify>command that exits 0 on success</verify>
  <done>What "done" looks like</done>
</task>
```

- **depends_on** — (optional) comma-separated task IDs this task depends on. If omitted, the task depends on all prior tasks in its phase.
- **files** — only touch these files for this task
- **action** — follow these instructions precisely
- **verify** — run this command after implementation; it must exit 0
- **done** — the acceptance criteria

### Updating STATE.md

After each task, append a line to STATE.md using this exact format:

```markdown
[✓] 1.1: Task name — brief notes
```

If a task fails:

```markdown
[✗] 1.1: Task name — what went wrong
```

**When you finish all tasks in a phase**, append this line to STATE.md:

```markdown
## Phase Complete: Phase 1: Foundation
```

Then run `sago replan` before starting the next phase. This reviews completed work and provides context for the remaining phases.

### Maintaining the Resume Point

After each task, update the `## Resume Point` section in STATE.md so you can resume efficiently if interrupted.

**After a successful task:**

```markdown
## Resume Point

* **Last Completed:** 1.2: Add Configuration
* **Next Task:** 2.1: Build CLI
* **Next Action:** Create Typer CLI application
* **Failure Reason:** None
* **Checkpoint:** sago-checkpoint-1.2
```

**After a failed verification:**

```markdown
## Resume Point

* **Last Completed:** 1.1: Initialize Project
* **Next Task:** 1.2: Add Configuration (retry)
* **Next Action:** Fix config loading for nested keys
* **Failure Reason:** pytest tests/test_config.py exited 1 — KeyError on nested.key
* **Checkpoint:** sago-checkpoint-1.1
```

After each successful task, create a git tag: `git tag sago-checkpoint-{task_id}` (e.g., `git tag sago-checkpoint-1.2`). This gives you a rollback point if a later task breaks something.

## Rules

- Follow the plan. Do not add features, refactor code, or make improvements beyond what each task specifies.
- Follow task dependencies — check `depends_on` to determine task order. Tasks without `depends_on` depend on all prior tasks in their phase.
- If a `<dependencies>` block exists in PLAN.md, install those packages before starting Phase 1.
- Every task must pass its verify command before you move on.
- If you're stuck on a task, document the blocker in STATE.md and move to the next task.
- Run `sago replan` between phases for review and context carry-forward.
