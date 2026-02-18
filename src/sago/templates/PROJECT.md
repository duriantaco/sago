# {{project_name}}

## Project Vision

A brief description of what you're building and why. The planner agent reads this to understand context.

**Example:**
> TaskFlow is a CLI task runner that reads YAML job definitions, resolves dependencies
> between jobs, and executes them in parallel where possible. It targets small teams
> who want Make-like automation without learning Make syntax.

## Tech Stack & Constraints

* **Language:** Python 3.12
* **Framework:** Typer (CLI), Pydantic (config)
* **Database:** SQLite (local job history)
* **Testing:** pytest

## Core Architecture

Describe the high-level structure: key modules, data flow, and patterns.

**Example:**
> Single-package CLI (`src/taskflow/`). YAML loader parses job files into a DAG.
> A scheduler walks the DAG and dispatches jobs to a thread pool. Each job writes
> structured logs to SQLite so `taskflow history` can show past runs.
