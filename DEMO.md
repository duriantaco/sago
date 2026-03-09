# Sago Demo

## Quick demo (no API key)

```bash
pip install -e .
sago trace --demo
```

Opens the live dashboard with sample data. Walk through the Feed and Log tabs.

## Core commands

| Command | What it does |
|---|---|
| `sago init` | Scaffold a new project (PROJECT.md, REQUIREMENTS.md, CLAUDE.md, etc.) |
| `sago plan` | Read PROJECT.md + REQUIREMENTS.md, call LLM, write PLAN.md with atomic tasks |
| `sago checkpoint` | Record task progress in STATE.md (the agent calls this, not manual editing) |
| `sago next` | Show the next actionable task with full details and context |
| `sago status` | Show project progress including resume point |
| `sago replan` | Update PLAN.md based on feedback without regenerating from scratch |
| `sago watch` | Launch mission control dashboard to monitor your coding agent |
| `sago judge` | Configure a separate LLM for post-phase code review |

## Full demo

### 1. Create a project

```bash
sago init site-gen --prompt "A static site generator that reads markdown files from a content/ directory, converts them to HTML with a base template, and outputs a complete site to build/ with an index page listing all posts"
cd site-gen
```

This creates:

| File | What it is | Who writes it |
|---|---|---|
| `PROJECT.md` | Vision, tech stack, architecture | LLM (from your `--prompt`) |
| `REQUIREMENTS.md` | Feature list in `* [ ] REQ-N:` format | LLM (from your `--prompt`) |
| `IMPORTANT.md` | Custom instructions for the coding agent | Template (user edits) |
| `CLAUDE.md` | Instructions that teach coding agents how to follow the plan | Template |
| `PLAN.md` | Placeholder — gets filled by `sago plan` | Template (then LLM overwrites) |
| `STATE.md` | Progress tracker with resume point | Template (`sago checkpoint` updates) |

### 2. Generate the plan

```bash
sago plan
```

Review PLAN.md. It contains atomic tasks in XML with verify commands, organized into phases. Edit it if you want — add tasks, change verify commands, reorder phases. Nothing executes until your coding agent reads it.

### 3. Hand off to your coding agent

Sago doesn't execute — your coding agent does. Point your agent at the project:

**Claude Code:**
```bash
cd site-gen
claude   # reads CLAUDE.md automatically
```

**Cursor / Aider / other agents:**
Open the project directory. The agent reads CLAUDE.md for instructions on how to follow the plan and use `sago checkpoint` to record progress.

### 4. Monitor progress

```bash
sago status -d        # per-task breakdown with resume point
sago watch            # live dashboard in your browser
```

### 5. Iterate on the plan

After a phase completes (or fails), update the plan based on what you've learned:

```bash
sago replan                              # interactive — prompts for feedback
sago replan -f "add error handling" -y   # non-interactive — scripted
```

Replan reviews completed work, shows a diff of changes (added/modified/removed tasks), and asks for confirmation before applying.

## `.env`

```bash
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o
LLM_API_KEY=sk-your-key
LOG_LEVEL=WARNING
```

## If something goes wrong

| Problem | Fix |
|---|---|
| Dashboard doesn't open | `sago trace` to open manually |
| No API key | `sago trace --demo` for sample data |
| Plan looks wrong | Edit PLAN.md directly or run `sago replan` |
| Agent lost its place | Check the resume point in STATE.md |