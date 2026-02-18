"""Example demonstrating the sago agent workflow.

This example shows how to use the agent system to:
1. Generate a plan from requirements
2. Execute tasks with dependency resolution
3. Verify task completion
4. Track progress
"""

import asyncio
import logging
from pathlib import Path

from sago.agents import Orchestrator
from sago.core.config import Config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


async def example_1_plan_only():
    """Example 1: Generate plan from requirements."""
    print("\n" + "=" * 80)
    print("EXAMPLE 1: Generate Plan Only")
    print("=" * 80 + "\n")

    # Setup
    config = Config()
    orchestrator = Orchestrator(config=config)
    project_path = Path("./example-project")

    # Ensure project has requirements
    project_path.mkdir(exist_ok=True)
    (project_path / "REQUIREMENTS.md").write_text(
        """# Requirements

## Features
- [ ] User authentication with email/password
- [ ] SQLite database for user storage
- [ ] Password hashing with bcrypt
- [ ] Basic REST API endpoints

## Technical Requirements
- Python 3.11+
- FastAPI framework
- SQLAlchemy ORM
- Pytest for testing
"""
    )

    # Generate plan only (don't execute)
    result = await orchestrator.run_workflow(
        project_path=project_path,
        plan=True,  # Generate plan
        execute=False,  # Don't execute yet
    )

    if result.success:
        print("✓ Plan generated successfully!")
        print(f"  Plan file: {project_path / 'PLAN.md'}")
    else:
        print(f"✗ Plan generation failed: {result.error}")


async def example_2_execute_plan():
    """Example 2: Execute existing plan."""
    print("\n" + "=" * 80)
    print("EXAMPLE 2: Execute Existing Plan")
    print("=" * 80 + "\n")

    # Setup
    config = Config()
    orchestrator = Orchestrator(config=config)
    project_path = Path("./example-project")

    # Create a simple plan for demonstration
    (project_path / "PLAN.md").write_text(
        """# PLAN.md

```xml
<phases>
    <phase name="Phase 1: Setup">
        <description>Project setup</description>

        <task id="1.1">
            <name>Create config file</name>
            <files>config.py</files>
            <action>
                Create a simple config.py with:
                - DATABASE_URL constant
                - SECRET_KEY constant
                - Basic configuration class
            </action>
            <verify>python -c "import config; print('OK')"</verify>
            <done>Config file exists and is importable</done>
        </task>

        <task id="1.2">
            <name>Create main file</name>
            <files>main.py config.py</files>
            <action>
                Create main.py that:
                - Imports config
                - Has a main() function
                - Prints "Hello from sago!"
            </action>
            <verify>python main.py</verify>
            <done>Main file runs successfully</done>
        </task>
    </phase>
</phases>
```
"""
    )

    # Execute plan with verification
    result = await orchestrator.run_workflow(
        project_path=project_path,
        plan=False,  # Use existing plan
        execute=True,  # Execute tasks
        verify=True,  # Verify each task
        max_retries=2,  # Retry failed tasks
    )

    # Show results
    print(f"\nWorkflow completed!")
    print(f"  Status: {'✓ SUCCESS' if result.success else '✗ FAILED'}")
    print(f"  Total tasks: {result.total_tasks}")
    print(f"  Completed: {result.completed_tasks}")
    print(f"  Failed: {result.failed_tasks}")
    print(f"  Duration: {result.total_duration:.1f}s")

    # Show per-task results
    print("\nTask Results:")
    for task_exec in result.task_executions:
        status = "✓" if task_exec.success else "✗"
        print(f"  {status} {task_exec.task.id}: {task_exec.task.name}")
        print(f"     Duration: {task_exec.duration:.2f}s")
        if task_exec.retry_count > 0:
            print(f"     Retries: {task_exec.retry_count}")
        if not task_exec.success:
            print(f"     Error: {task_exec.execution_result.error}")


async def example_3_full_workflow():
    """Example 3: Complete workflow (plan + execute)."""
    print("\n" + "=" * 80)
    print("EXAMPLE 3: Complete Workflow (Plan + Execute)")
    print("=" * 80 + "\n")

    # Setup
    config = Config()
    orchestrator = Orchestrator(config=config)
    project_path = Path("./example-project-full")
    project_path.mkdir(exist_ok=True)

    # Create requirements
    (project_path / "PROJECT.md").write_text(
        """# Example Project

A simple Python calculator library.

## Goals
- Basic arithmetic operations
- Well-tested code
- Type hints
"""
    )

    (project_path / "REQUIREMENTS.md").write_text(
        """# Requirements

## Features
- [ ] Add two numbers
- [ ] Subtract two numbers
- [ ] Multiply two numbers
- [ ] Divide two numbers (with zero check)

## Testing
- [ ] Unit tests for all operations
- [ ] Test edge cases
"""
    )

    # Run complete workflow
    result = await orchestrator.run_workflow(
        project_path=project_path,
        plan=True,  # Generate plan
        execute=True,  # Execute tasks
        verify=True,  # Verify tasks
        max_retries=1,
        continue_on_failure=True,  # Try to complete as many tasks as possible
    )

    # Show results
    print(f"\nComplete workflow finished!")
    print(f"  Success: {result.success}")
    print(f"  Completed: {result.completed_tasks}/{result.total_tasks}")
    print(f"  Failed: {result.failed_tasks}")
    print(f"  Skipped: {result.skipped_tasks}")
    print(f"  Total time: {result.total_duration:.1f}s")


async def example_4_error_handling():
    """Example 4: Error handling and recovery."""
    print("\n" + "=" * 80)
    print("EXAMPLE 4: Error Handling")
    print("=" * 80 + "\n")

    config = Config()
    orchestrator = Orchestrator(config=config)
    project_path = Path("./example-project-errors")
    project_path.mkdir(exist_ok=True)

    # Create plan with intentional error
    (project_path / "PLAN.md").write_text(
        """# PLAN.md

```xml
<phases>
    <phase name="Phase 1: Test Errors">
        <description>Demonstrate error handling</description>

        <task id="1.1">
            <name>This will fail verification</name>
            <files>test.py</files>
            <action>Create test.py with syntax error</action>
            <verify>python test.py</verify>
            <done>Test passes</done>
        </task>
    </phase>
</phases>
```
"""
    )

    # Execute with error handling
    try:
        result = await orchestrator.run_workflow(
            project_path=project_path,
            plan=False,
            execute=True,
            verify=True,
            max_retries=2,  # Try 3 times total
            continue_on_failure=False,  # Stop on failure
        )

        if not result.success:
            print("\n⚠ Workflow failed as expected")
            print(f"  Error: {result.error or 'Task verification failed'}")

            # Show failed task details
            for task_exec in result.task_executions:
                if not task_exec.success:
                    print(f"\nFailed Task: {task_exec.task.id}")
                    print(f"  Retries attempted: {task_exec.retry_count}")
                    print(f"  Execution error: {task_exec.execution_result.error}")
                    if task_exec.verification_result:
                        print(
                            f"  Verification error: {task_exec.verification_result.error}"
                        )

    except Exception as e:
        print(f"✗ Exception caught: {e}")


async def example_5_dependency_visualization():
    """Example 5: Visualize task dependencies."""
    print("\n" + "=" * 80)
    print("EXAMPLE 5: Dependency Visualization")
    print("=" * 80 + "\n")

    from sago.agents import DependencyResolver
    from sago.core.parser import Task

    # Create sample tasks with dependencies
    tasks = [
        Task(
            id="1.1",
            name="Create database schema",
            files=["schema.sql"],
            action="Create schema",
            verify="sqlite3 test.db < schema.sql",
            done="Schema created",
            phase_name="Phase 1",
        ),
        Task(
            id="1.2",
            name="Create models",
            files=["models.py", "schema.sql"],  # Depends on schema
            action="Create SQLAlchemy models",
            verify="python -c 'import models'",
            done="Models importable",
            phase_name="Phase 1",
        ),
        Task(
            id="2.1",
            name="Create API routes",
            files=["routes.py", "models.py"],  # Depends on models
            action="Create FastAPI routes",
            verify="python -c 'import routes'",
            done="Routes importable",
            phase_name="Phase 2",
        ),
        Task(
            id="2.2",
            name="Create tests",
            files=["tests.py"],  # Independent
            action="Create test suite",
            verify="pytest tests.py",
            done="Tests pass",
            phase_name="Phase 2",
        ),
    ]

    # Resolve dependencies
    resolver = DependencyResolver()

    print("Task Dependency Graph:")
    print(resolver.visualize_dependencies(tasks))

    # Show execution waves
    waves = resolver.resolve(tasks)

    print(f"\nExecution Plan ({len(waves)} waves):")
    for i, wave in enumerate(waves, 1):
        task_ids = [task.id for task in wave]
        print(f"\n  Wave {i}: {', '.join(task_ids)}")
        if len(wave) > 1:
            print(f"    → These tasks run in PARALLEL")
        else:
            print(f"    → This task runs SEQUENTIALLY")


async def main():
    """Run all examples."""
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "sago Agent System Examples" + " " * 32 + "║")
    print("╚" + "=" * 78 + "╝")

    # Run examples
    # await example_1_plan_only()
    # await example_2_execute_plan()
    # await example_3_full_workflow()
    # await example_4_error_handling()
    await example_5_dependency_visualization()

    print("\n" + "=" * 80)
    print("All examples completed!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
