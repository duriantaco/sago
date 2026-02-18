# Agent System Documentation

The sago agent system enables fully automated code generation and execution through a multi-agent architecture.

## Overview

The agent system consists of specialized agents that work together to:

1. **Plan** - Generate structured task plans from requirements
2. **Execute** - Write code to complete tasks
3. **Verify** - Validate task completion
4. **Orchestrate** - Coordinate the entire workflow

## Architecture

### Core Components

#### 1. BaseAgent

Abstract base class providing common functionality for all agents:

```python
from sago.agents import BaseAgent, AgentResult

class CustomAgent(BaseAgent):
    async def execute(self, context: dict[str, Any]) -> AgentResult:
        return self._create_result(
            status=AgentStatus.SUCCESS,
            output="Task completed",
            metadata={}
        )
```

**Features:**
- LLM integration via LiteLLM
- Standardized result format
- Built-in logging
- Error handling

#### 2. PlannerAgent

Generates PLAN.md files from project requirements and context.

**Input:**
- PROJECT.md
- REQUIREMENTS.md
- ROADMAP.md
- STATE.md

**Output:**
- PLAN.md with XML-structured tasks

**Usage:**
```python
from pathlib import Path
from sago.agents import PlannerAgent
from sago.core.config import Config

config = Config()
planner = PlannerAgent(config=config)

result = await planner.execute({
    "project_path": Path("./my-project")
})

if result.success:
    print(f"Plan generated: {result.metadata['plan_path']}")
```

**Plan Structure:**
```xml
<phases>
    <phase name="Phase 1: Foundation">
        <description>Set up project structure</description>

        <task id="1.1">
            <name>Initialize Python Project</name>
            <files>
                pyproject.toml
                src/__init__.py
            </files>
            <action>
                Create project structure with:
                - pyproject.toml with dependencies
                - src/__init__.py with version info
            </action>
            <verify>
                python -c "import sys; sys.path.insert(0, 'src'); import myproject"
            </verify>
            <done>Project imports successfully</done>
        </task>
    </phase>
</phases>
```

#### 3. ExecutorAgent

Generates and applies code changes for tasks.

**Process:**
1. Reads task specification
2. Builds context (existing files, project info)
3. Uses LLM to generate code
4. Applies changes to filesystem

**Usage:**
```python
from sago.agents import ExecutorAgent
from sago.core.parser import Task

executor = ExecutorAgent(config=config)

task = Task(
    id="1.1",
    name="Create config module",
    files=["config.py"],
    action="Create configuration with environment variables",
    verify="python -c 'import config'",
    done="Config module exists",
    phase_name="Phase 1"
)

result = await executor.execute({
    "task": task,
    "project_path": Path("./my-project")
})
```

**Generated Code Format:**
The LLM generates code using this format:

```
=== FILE: src/config.py ===
```python
# Complete file content here
class Config:
    def __init__(self):
        self.api_key = os.getenv("API_KEY")
\```
```

#### 4. VerifierAgent

Runs verification commands to ensure task completion.

**Features:**
- Executes shell commands with timeout
- Captures stdout/stderr
- Returns detailed diagnostic information

**Usage:**
```python
from sago.agents import VerifierAgent

verifier = VerifierAgent(config=config)

result = await verifier.execute({
    "task": task,
    "project_path": Path("./my-project")
})

if result.success:
    print("Task verified successfully")
else:
    print(f"Verification failed: {result.error}")
```

#### 5. DependencyResolver

Analyzes task dependencies and creates execution waves.

**Algorithm:**
1. Parses file dependencies between tasks
2. Builds dependency graph
3. Detects circular dependencies
4. Performs topological sort
5. Groups independent tasks into "waves"

**Usage:**
```python
from sago.agents import DependencyResolver

resolver = DependencyResolver()

waves = resolver.resolve(tasks)

# Wave 1: [task1.1, task2.1]  # Can run in parallel
# Wave 2: [task1.2]             # Depends on wave 1
# Wave 3: [task1.3, task2.2]    # Can run in parallel

ordered_tasks = resolver.get_task_order(tasks)

print(resolver.visualize_dependencies(tasks))
```

**Dependency Detection:**
- First file in task's file list = file being created
- Subsequent files = dependencies
- If task A creates `config.py` and task B lists `config.py` as a dependency, B waits for A

**Circular Dependency Detection:**
Uses DFS to detect cycles in the dependency graph. Raises `CircularDependencyError` if found.

#### 6. Orchestrator

Coordinates all agents to execute complete workflows.

**Workflow Stages:**

1. **Plan Generation** (optional)
   - Generates PLAN.md if it doesn't exist
   - Uses PlannerAgent

2. **Plan Parsing**
   - Reads PLAN.md
   - Extracts phases and tasks
   - Validates structure

3. **Dependency Resolution**
   - Builds dependency graph
   - Creates execution waves
   - Detects circular dependencies

4. **Task Execution**
   - Executes waves in order
   - Parallel execution within waves
   - Retry logic per task

5. **Task Verification**
   - Runs verification commands
   - Validates task completion
   - Reports errors

6. **State Updates**
   - Updates STATE.md after each task
   - Logs completion status
   - Records errors

**Usage:**
```python
from sago.agents import Orchestrator
from pathlib import Path

orchestrator = Orchestrator(config=config)

result = await orchestrator.run_workflow(
    project_path=Path("./my-project"),
    plan=True,
    execute=True,
    verify=True,
    max_retries=2,
    continue_on_failure=False
)

print(f"Success: {result.success}")
print(f"Completed: {result.completed_tasks}/{result.total_tasks}")
print(f"Failed: {result.failed_tasks}")
print(f"Duration: {result.total_duration:.1f}s")

for task_exec in result.task_executions:
    print(f"{task_exec.task.id}: {task_exec.duration:.1f}s")
```

**Advanced Options:**

```python
result = await orchestrator.run_workflow(
    project_path=path,
    plan=True,
    execute=False
)

result = await orchestrator.run_workflow(
    project_path=path,
    plan=False,
    execute=True,
    verify=False
)

result = await orchestrator.run_workflow(
    project_path=path,
    continue_on_failure=True,
    max_retries=3
)
```

## Execution Flow

```
┌─────────────────────────────────────────────────┐
│ 1. PLAN GENERATION                              │
│    • Load project context files                 │
│    • Generate PLAN.md with XML tasks            │
│    • Validate plan structure                    │
└───────────────┬─────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────┐
│ 2. DEPENDENCY RESOLUTION                        │
│    • Parse tasks from PLAN.md                   │
│    • Build dependency graph                     │
│    • Detect circular dependencies               │
│    • Create execution waves                     │
└───────────────┬─────────────────────────────────┘
                ▼
┌─────────────────────────────────────────────────┐
│ 3. WAVE EXECUTION (Parallel)                    │
│                                                  │
│    Wave 1: [Task 1.1, Task 2.1] ──► Execute     │
│            ├─► Executor Agent                    │
│            ├─► Verifier Agent                    │
│            └─► Update STATE.md                   │
│                                                  │
│    Wave 2: [Task 1.2] ──────────► Execute       │
│            ├─► Executor Agent                    │
│            ├─► Verifier Agent                    │
│            └─► Update STATE.md                   │
└─────────────────────────────────────────────────┘
```

## Error Handling

### Task Execution Errors

```python
result = await orchestrator.run_workflow(
    project_path=path,
    max_retries=2
)

for task_exec in result.task_executions:
    if not task_exec.success:
        print(f"Task {task_exec.task.id} failed:")
        print(f"  Execution: {task_exec.execution_result.error}")
        if task_exec.verification_result:
            print(f"  Verification: {task_exec.verification_result.error}")
        print(f"  Retries: {task_exec.retry_count}")
```

### Circular Dependencies

```python
from sago.agents.dependencies import CircularDependencyError

try:
    result = await orchestrator.run_workflow(project_path=path)
except CircularDependencyError as e:
    print(f"Circular dependency detected: {e}")
    # Fix PLAN.md to remove circular dependencies
```

### LLM Failures

All agents have built-in retry logic for LLM calls:

- Automatic retry on transient failures
- Configurable timeout
- Error logging with context

## Best Practices

### 1. Writing Good Task Specifications

**DO:**
```xml
<task id="1.1">
    <name>Create authentication module</name>
    <files>
        src/auth.py
        tests/test_auth.py
    </files>
    <action>
        Create authentication module with:
        - User class with email/password fields
        - hash_password() using bcrypt
        - verify_password() method
        - Include type hints and docstrings
    </action>
    <verify>pytest tests/test_auth.py -v</verify>
    <done>Authentication tests pass</done>
</task>
```

**DON'T:**
```xml
<task id="1.1">
    <name>Setup auth</name>
    <files>auth.py</files>
    <action>Add authentication</action>
    <verify>python auth.py</verify>
    <done>Done</done>
</task>
```

### 2. Atomic Tasks

Each task should be:
- **Completable in one execution** - Not "build entire API"
- **Independently testable** - Has clear verification
- **Well-defined** - Specific files and requirements

### 3. Verification Commands

Good verification commands:
```bash
# Run specific tests
pytest tests/test_module.py -v

# Import and basic check
python -c "from myproject import Module; assert Module.VERSION == '1.0'"

# Lint/type check
mypy src/module.py --strict

# Run script
python scripts/verify_setup.py
```

### 4. Dependencies

- Keep dependency chains short
- Prefer parallel execution (independent tasks)
- Group related tasks in phases
- Use file dependencies implicitly (don't specify deps explicitly)

## Configuration

Configure agent behavior in `.env` or environment:

```bash
sago_LLM_PROVIDER=openai
sago_LLM_MODEL=gpt-4-turbo-preview
sago_LLM_API_KEY=sk-...
sago_LLM_TEMPERATURE=0.3
sago_LLM_MAX_TOKENS=4000

sago_MAX_RETRIES=2
sago_VERIFY_TIMEOUT=300
sago_EXECUTION_TIMEOUT=600  # 10 minutes

# Compression (optional)
sago_MAX_CONTEXT_TOKENS=4000
sago_COMPRESSION_THRESHOLD=0.75
sago_COMPRESSION_STRATEGY=sliding_window
```

## Monitoring and Debugging

### Enable Debug Logging

```python
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

result = await orchestrator.run_workflow(project_path=path)
```

### Check STATE.md

STATE.md is automatically updated after each task:

```markdown
# Project State

## Completed Tasks

- [✓] 1.1: Create config module (2024-02-16 10:30:15)
- [✓] 1.2: Create database module (2024-02-16 10:31:42)
- [✗] 1.3: Create models (2024-02-16 10:33:01)
  - Error: ImportError: cannot import name 'Base'
```

### Inspect Workflow Results

```python
result = await orchestrator.run_workflow(project_path=path)

print(result.to_dict())

for task_exec in result.task_executions:
    print(f"\nTask: {task_exec.task.id} - {task_exec.task.name}")
    print(f"  Status: {'✓' if task_exec.success else '✗'}")
    print(f"  Duration: {task_exec.duration:.2f}s")
    print(f"  Retries: {task_exec.retry_count}")

    if not task_exec.success:
        print(f"  Execution Error: {task_exec.execution_result.error}")
        if task_exec.verification_result:
            print(f"  Verification Error: {task_exec.verification_result.error}")
```

## Performance

### Parallel Execution

The orchestrator executes independent tasks in parallel:

```python
# Sequential execution (if all tasks depend on each other)
# Total time = sum of all task times
# 1.1 (30s) -> 1.2 (45s) -> 1.3 (60s) = 135s

# Parallel execution (if tasks are independent)
# Total time = longest task time
# 1.1 (30s) ─┐
# 1.2 (45s) ─┼─> max(30, 45, 60) = 60s
# 1.3 (60s) ─┘
```

### LLM Token Usage

Approximate token usage per task:

- **PlannerAgent**: 1,000-3,000 tokens (generates entire plan)
- **ExecutorAgent**: 500-2,000 tokens per task (generates code)
- **VerifierAgent**: No LLM calls (runs shell commands)

**Optimization:**
- Use context compression for large codebases
- Provide focused task descriptions
- Limit file sizes in context

### Retry Strategy

Failed tasks are retried with exponential backoff:

```python
# Attempt 1: Execute immediately
# Attempt 2: Wait 1s, retry
# Attempt 3: Wait 2s, retry
# Fail after max_retries attempts
```

## Integration with CLI

The agent system will be integrated into the CLI:

```bash
# Generate plan from requirements
sago plan

# Execute tasks from plan
sago execute

# Run complete workflow (plan + execute)
sago run

# Check status
sago status
```

## Testing

Run agent system tests:

```bash
pytest tests/test_dependencies.py tests/test_orchestrator.py -v

pytest tests/test_orchestrator.py::test_run_workflow_plan_exists -v

# With coverage
pytest tests/ --cov=src/sago/agents --cov-report=html
```

## Troubleshooting

### "Circular dependency detected"

**Cause:** Tasks form a dependency cycle.

**Solution:** Check PLAN.md for tasks that depend on each other:
```
Task A needs file from Task B
Task B needs file from Task C
Task C needs file from Task A  ← Circular!
```

### "Plan generation failed"

**Cause:** Invalid project context or LLM error.

**Solution:**
1. Check that PROJECT.md and REQUIREMENTS.md exist
2. Verify LLM API key is valid
3. Check LLM service status
4. Review error message in result.error

### "Task execution failed"

**Cause:** LLM generated invalid code or execution error.

**Solution:**
1. Check execution_result.error for details
2. Review generated code in project files
3. Manually fix issues
4. Re-run with `continue_on_failure=True`

### "Verification timeout"

**Cause:** Verification command took too long.

**Solution:**
1. Increase `sago_VERIFY_TIMEOUT`
2. Simplify verification command
3. Check for hanging processes

## Future Enhancements

Planned improvements:

1. **Git Integration** - Automatic commits per task
2. **Interactive Mode** - Manual approval before each task
3. **Rollback Support** - Undo failed tasks
4. **Multi-project Support** - Coordinate multiple repos
5. **Human-in-the-loop** - Request clarification when needed
6. **Incremental Planning** - Adjust plan based on results
7. **Cost Tracking** - Monitor LLM API costs
8. **Web Dashboard** - Visual workflow monitoring

## API Reference

See individual agent files for detailed API documentation:

- [base.py](../src/sago/agents/base.py) - BaseAgent, AgentResult, AgentStatus
- [planner.py](../src/sago/agents/planner.py) - PlannerAgent
- [executor.py](../src/sago/agents/executor.py) - ExecutorAgent
- [verifier.py](../src/sago/agents/verifier.py) - VerifierAgent
- [dependencies.py](../src/sago/agents/dependencies.py) - DependencyResolver
- [orchestrator.py](../src/sago/agents/orchestrator.py) - Orchestrator

---

**Built with Claude Code Control Protocol (sago)**
