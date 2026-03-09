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

### Recording progress with `sago checkpoint`

**After each task**, run `sago checkpoint` to record progress. Do NOT edit STATE.md manually — the tool owns the file format.

**After a successful task:**

```bash
sago checkpoint 1.1 --notes "Config module working" --next "1.2: Create main" --next-action "Create main module"
```

**After a failed verification:**

```bash
sago checkpoint 1.2 --status failed --notes "pytest exited 1 — KeyError on nested.key" --next "1.2: Create main (retry)" --next-action "Fix config loading"
```

**Recording key decisions:**

```bash
sago checkpoint 2.1 --notes "Auth system done" -d "Chose JWT over sessions" -d "Using bcrypt for passwords"
```

**When you finish all tasks in a phase**, run `sago replan` before starting the next phase. This reviews completed work and provides context for the remaining phases.

The checkpoint command automatically:
- Updates STATE.md with the task result
- Maintains the Resume Point for crash recovery
- Creates a git tag (`sago-checkpoint-{task_id}`) on success
- Tracks key architectural decisions

## Rules

- Follow the plan. Do not add features, refactor code, or make improvements beyond what each task specifies.
- Follow task dependencies — check `depends_on` to determine task order. Tasks without `depends_on` depend on all prior tasks in their phase.
- If a `<dependencies>` block exists in PLAN.md, install those packages before starting Phase 1.
- Every task must pass its verify command before you move on.
- **Never edit STATE.md directly.** Always use `sago checkpoint` to record progress.
- If you're stuck on a task, run `sago checkpoint <id> --status failed --notes "blocker description"` and move on.
- Run `sago replan` between phases for review and context carry-forward.
