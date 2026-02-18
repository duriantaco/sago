# PLAN.md

> **CRITICAL COMPONENT:** This file uses a specific XML schema to force the AI into "Atomic Task" mode.

```xml
<phases>
    <phase name="Phase 1: Foundation">
        <description>Set up project structure, core utilities, and configuration management</description>

        <task id="1.1">
            <name>Initialize Python Project Structure</name>
            <files>
                pyproject.toml
                src/sago/__init__.py
                src/sago/core/__init__.py
                src/sago/agents/__init__.py
                src/sago/blocker/__init__.py
                src/sago/utils/__init__.py
                tests/__init__.py
                .planning/.gitkeep
            </files>
            <action>
                Create the complete project structure with pyproject.toml using Poetry or modern Python packaging.
                Set up dependencies: typer, fastapi, pydantic, litellm, rich, pytest, black, ruff.
                Python version requirement: 3.11+
                Add all __init__.py files for proper package structure.
            </action>
            <verify>
                python -c "import sago; print('OK')"
            </verify>
            <done>Project imports successfully without errors</done>
        </task>

        <task id="1.2">
            <name>Create Configuration Management</name>
            <files>src/sago/core/config.py</files>
            <action>
                Implement a Pydantic BaseSettings class for configuration.
                Support .env file loading with environment variables.
                Include settings for: LLM provider, model name, planning directory path, log level.
                Use 12-factor app pattern.
            </action>
            <verify>
                pytest tests/test_config.py::test_config_loads_env
            </verify>
            <done>Config loads from .env and provides type-safe settings</done>
        </task>

        <task id="1.3">
            <name>Implement Template Management System</name>
            <files>src/sago/core/project.py</files>
            <action>
                Create ProjectManager class that can:
                - Initialize new projects with all 7 markdown templates (PROJECT.md, REQUIREMENTS.md, ROADMAP.md, STATE.md, PLAN.md, SUMMARY.md, IMPORTANT.md)
                - Read/write/update markdown files
                - Create .planning/ directory structure
                Use the existing templates from the repo as defaults.
            </action>
            <verify>
                pytest tests/test_project.py::test_init_creates_templates
            </verify>
            <done>Can initialize a new project with all template files</done>
        </task>

        <task id="1.4">
            <name>Build Markdown/XML Parser</name>
            <files>src/sago/core/parser.py</files>
            <action>
                Implement MarkdownParser class that can:
                - Parse XML task blocks from PLAN.md
                - Extract requirements from REQUIREMENTS.md (parse checkboxes)
                - Parse roadmap milestones from ROADMAP.md
                - Read STATE.md context
                Use xml.etree.ElementTree for XML parsing.
                Return Pydantic models for type safety.
            </action>
            <verify>
                pytest tests/test_parser.py::test_parse_xml_tasks
            </verify>
            <done>Parser extracts all tasks with proper structure</done>
        </task>
    </phase>

    <phase name="Phase 2: Website Blocker">
        <description>Implement hosts file manipulation for focus mode</description>

        <task id="2.1">
            <name>Create HostsManager Class</name>
            <files>src/sago/blocker/manager.py</files>
            <action>
                Implement HostsManager class with methods:
                - read_hosts(): Read and parse /etc/hosts (Unix) or C:\Windows\System32\drivers\etc\hosts (Windows)
                - backup_hosts(): Create .bak file before modifications
                - block_sites(domains: List[str]): Add 0.0.0.0 redirects
                - unblock_sites(domains: List[str]): Remove redirects
                - is_blocked(domain: str): Check if domain is blocked
                Handle permissions gracefully, provide clear error messages.
                Detect OS automatically (platform.system()).
            </action>
            <verify>
                pytest tests/test_blocker.py::test_hosts_manager_reads
            </verify>
            <done>Can read, backup, and modify hosts file safely</done>
        </task>

        <task id="2.2">
            <name>Add Elevation/Sudo Support</name>
            <files>src/sago/utils/elevation.py</files>
            <action>
                Create utility functions for privilege escalation:
                - requires_elevation() decorator for functions needing root/admin
                - re_exec_with_sudo() to restart process with elevated privileges
                Support both Unix (sudo) and Windows (UAC via ctypes).
                Handle user cancellation gracefully.
            </action>
            <verify>
                pytest tests/test_elevation.py::test_detects_elevation_needed
            </verify>
            <done>Functions properly request elevation when needed</done>
        </task>
    </phase>

    <phase name="Phase 3: LLM Integration">
        <description>Set up AI agent orchestration using LiteLLM</description>

        <task id="3.1">
            <name>Create LLM Client Wrapper</name>
            <files>src/sago/utils/llm.py</files>
            <action>
                Implement LLMClient class wrapping litellm:
                - chat_completion(messages, model, temperature, max_tokens) method
                - Support streaming responses with callback
                - Handle rate limits and retries with exponential backoff
                - Log all API calls for debugging
                Use tenacity library for retries.
            </action>
            <verify>
                pytest tests/test_llm.py::test_llm_client_calls_api
            </verify>
            <done>LLM client successfully makes API calls with retry logic</done>
        </task>

        <task id="3.2">
            <name>Implement Base Agent Class</name>
            <files>src/sago/agents/__init__.py</files>
            <action>
                Create abstract BaseAgent class with:
                - __init__(llm_client, config)
                - execute(context: Dict) -> AgentResult abstract method
                - _build_prompt(context: Dict) -> str helper
                - _parse_response(response: str) -> Dict helper
                Define AgentResult Pydantic model with status, output, metadata.
            </action>
            <verify>
                pytest tests/test_agents.py::test_base_agent_interface
            </verify>
            <done>Base agent provides clean interface for subclasses</done>
        </task>

        <task id="3.3">
            <name>Build Planner Agent</name>
            <files>src/sago/agents/planner.py</files>
            <action>
                Implement PlannerAgent(BaseAgent) that:
                - Takes PROJECT.md and REQUIREMENTS.md as context
                - Generates XML-formatted PLAN.md with atomic tasks
                - Uses structured prompting to force atomic task breakdown
                - Validates XML output before returning
                Prompt should enforce: task names, files, actions, verify commands, done criteria.
            </action>
            <verify>
                pytest tests/test_agents.py::test_planner_generates_xml
            </verify>
            <done>Planner generates valid XML plans from requirements</done>
        </task>

        <task id="3.4">
            <name>Build Executor Agent</name>
            <files>src/sago/agents/executor.py</files>
            <action>
                Implement ExecutorAgent(BaseAgent) that:
                - Takes a single Task object from parsed PLAN.md
                - Reads referenced files for context
                - Generates code/changes for the task
                - Returns structured output (files to create/modify)
                Should NOT actually write files (that's orchestrator's job).
            </action>
            <verify>
                pytest tests/test_agents.py::test_executor_processes_task
            </verify>
            <done>Executor generates code changes for individual tasks</done>
        </task>

        <task id="3.5">
            <name>Build Verifier Agent</name>
            <files>src/sago/agents/verifier.py</files>
            <action>
                Implement VerifierAgent(BaseAgent) that:
                - Takes task completion output and original task
                - Runs the verify command from the task
                - Parses command output to determine success/failure
                - Returns structured verification result with diagnostics
                Handle timeouts (30s default) and capture stderr.
            </action>
            <verify>
                pytest tests/test_agents.py::test_verifier_runs_commands
            </verify>
            <done>Verifier executes verify commands and returns results</done>
        </task>
    </phase>

    <phase name="Phase 4: Orchestration">
        <description>Coordinate multiple agents and manage workflow</description>

        <task id="4.1">
            <name>Implement Task Dependency Resolver</name>
            <files>src/sago/core/dependencies.py</files>
            <action>
                Create DependencyResolver class that:
                - Builds dependency graph from tasks (based on file dependencies)
                - Topologically sorts tasks into execution waves
                - detect_cycles() method to prevent deadlocks
                - get_next_wave() returns list of parallelizable tasks
                Use networkx library for graph operations.
            </action>
            <verify>
                pytest tests/test_dependencies.py::test_resolves_parallel_tasks
            </verify>
            <done>Resolver correctly identifies parallel task waves</done>
        </task>

        <task id="4.2">
            <name>Create Orchestrator</name>
            <files>src/sago/agents/orchestrator.py</files>
            <action>
                Implement Orchestrator class that:
                - Coordinates PlannerAgent, ExecutorAgent, VerifierAgent
                - Executes tasks in waves (parallel when possible)
                - Handles failures gracefully (pause, log, continue or abort)
                - Updates STATE.md after each task
                - Creates git commits per task (optional, configurable)
                - Tracks overall progress with rich progress bars
                Main method: run_project(project_path: Path) -> ExecutionResult
            </action>
            <verify>
                pytest tests/test_orchestrator.py::test_runs_full_workflow
            </verify>
            <done>Orchestrator executes multi-task plans successfully</done>
        </task>
    </phase>

    <phase name="Phase 5: CLI Interface">
        <description>Build user-facing CLI with Typer</description>

        <task id="5.1">
            <name>Implement Core CLI Commands</name>
            <files>src/sago/cli.py</files>
            <action>
                Create Typer app with commands:
                - init [project-name]: Initialize new project with templates
                - plan: Generate or update PLAN.md from requirements
                - execute [--parallel]: Run tasks from PLAN.md
                - verify [task-id]: Verify specific task completion
                - status: Show current project state and progress
                Use rich for beautiful output formatting.
                Add --verbose flag for debug logging.
            </action>
            <verify>
                sago --help
                sago init test-project
                ls test-project/PROJECT.md
            </verify>
            <done>CLI commands work and create expected outputs</done>
        </task>

        <task id="5.2">
            <name>Add Blocker CLI Commands</name>
            <files>src/sago/cli.py</files>
            <action>
                Add commands to existing CLI:
                - block [domain...]: Block websites via hosts file
                - unblock [domain...]: Unblock websites
                - block-list: Show currently blocked domains
                - focus [--duration]: Start focus session (block + timer)
                Integrate with HostsManager from Phase 2.
                Show warnings when elevation is required.
            </action>
            <verify>
                sago block example.com
                sago block-list
                sago unblock example.com
            </verify>
            <done>Blocker commands successfully modify hosts file</done>
        </task>

        <task id="5.3">
            <name>Add Interactive Init Wizard</name>
            <files>src/sago/cli.py</files>
            <action>
                Enhance 'init' command with interactive prompts:
                - Ask project name, description
                - Tech stack selection (multi-choice)
                - Testing requirements (coverage threshold)
                - Git initialization (yes/no)
                Use typer.prompt() and typer.confirm() for input.
                Use questionary library for rich multi-select.
                Populate PROJECT.md with answers.
            </action>
            <verify>
                echo -e "TestProject\nA test\n" | sago init --interactive
            </verify>
            <done>Interactive mode collects input and generates project</done>
        </task>
    </phase>

    <phase name="Phase 6: Git Integration">
        <description>Automated git operations for traceability</description>

        <task id="6.1">
            <name>Implement Git Helper</name>
            <files>src/sago/utils/git.py</files>
            <action>
                Create GitHelper class with methods:
                - init_repo(path): Initialize git repository
                - create_commit(message, files): Stage files and commit
                - create_branch(name): Create and checkout branch
                - get_status(): Return current git status
                - is_repo(path): Check if path is a git repo
                Use GitPython library for operations.
                Handle non-git directories gracefully.
            </action>
            <verify>
                pytest tests/test_git.py::test_creates_commits
            </verify>
            <done>Git helper performs all operations correctly</done>
        </task>

        <task id="6.2">
            <name>Add Atomic Commits to Orchestrator</name>
            <files>src/sago/agents/orchestrator.py</files>
            <action>
                Update Orchestrator to:
                - Commit after each successful task with message format:
                  "feat(phase-X): Complete task Y - [task name]"
                - Include task details in commit body
                - Skip commits if git is disabled in config
                - Tag commits with task metadata for traceability
            </action>
            <verify>
                pytest tests/test_orchestrator.py::test_creates_git_commits
            </verify>
            <done>Each completed task gets an individual git commit</done>
        </task>
    </phase>

    <phase name="Phase 7: Testing & Polish">
        <description>Comprehensive tests and documentation</description>

        <task id="7.1">
            <name>Write Unit Tests</name>
            <files>
                tests/test_config.py
                tests/test_project.py
                tests/test_parser.py
                tests/test_blocker.py
                tests/test_llm.py
                tests/test_agents.py
                tests/test_orchestrator.py
                tests/test_cli.py
                tests/test_git.py
            </files>
            <action>
                Create comprehensive pytest test suite:
                - Test all classes and methods
                - Use mocks for external dependencies (LLM API, file system)
                - Parametrize tests for different scenarios
                - Achieve minimum 80% code coverage
                Use pytest-cov for coverage reporting.
                Use pytest-mock for mocking.
            </action>
            <verify>
                pytest --cov=sago --cov-report=term-missing --cov-fail-under=80
            </verify>
            <done>All tests pass with 80%+ coverage</done>
        </task>

        <task id="7.2">
            <name>Create README and Documentation</name>
            <files>README.md, docs/quickstart.md, docs/architecture.md</files>
            <action>
                Write comprehensive documentation:
                - README.md: Installation, quick start, examples, features
                - docs/quickstart.md: Step-by-step tutorial
                - docs/architecture.md: System design, agent flow, XML schema
                Include screenshots using rich output captures.
                Add badges for tests, coverage, license.
            </action>
            <verify>
                grep "## Installation" README.md
            </verify>
            <done>Documentation is complete and well-formatted</done>
        </task>

        <task id="7.3">
            <name>Add Linting and Formatting</name>
            <files>pyproject.toml, .pre-commit-config.yaml</files>
            <action>
                Configure development tools:
                - Black for code formatting
                - Ruff for fast linting
                - MyPy for type checking
                - Pre-commit hooks for automation
                Add scripts to pyproject.toml for: lint, format, typecheck, test
            </action>
            <verify>
                black --check src/
                ruff check src/
                mypy src/
            </verify>
            <done>All linting and type checks pass</done>
        </task>
    </phase>

    <phase name="Phase 8: Advanced Features">
        <description>Nice-to-have enhancements</description>

        <task id="8.1">
            <name>Add Quick Mode</name>
            <files>src/sago/cli.py, src/sago/agents/quick.py</files>
            <action>
                Implement quick mode for ad-hoc tasks:
                - Command: sago quick "Add login form"
                - Skips full planning, executes immediately
                - Creates single-task PLAN.md
                - Still verifies and commits
                QuickAgent combines planning + execution in one shot.
            </action>
            <verify>
                sago quick "Add hello world function"
            </verify>
            <done>Quick mode executes simple tasks without full planning</done>
        </task>

        <task id="8.2">
            <name>Add Codebase Mapping</name>
            <files>src/sago/cli.py, src/sago/core/mapper.py</files>
            <action>
                Implement brownfield codebase analysis:
                - Command: sago map
                - Scans existing codebase structure
                - Generates CODEBASE.md with file tree and key modules
                - Uses tree-sitter for language-aware parsing
                - Helps AI understand existing projects before changes
            </action>
            <verify>
                sago map
                ls CODEBASE.md
            </verify>
            <done>Map command analyzes and documents existing codebases</done>
        </task>

        <task id="8.3">
            <name>Create Web Dashboard (Optional)</name>
            <files>src/sago/web/app.py, src/sago/web/templates/</files>
            <action>
                Build FastAPI web dashboard:
                - Route: / shows current project status
                - Route: /tasks shows task list with progress
                - Route: /logs streams execution logs
                - Route: /api/execute triggers execution
                Use WebSockets for real-time updates.
                Serve with uvicorn.
            </action>
            <verify>
                sago serve
                curl http://localhost:8000/
            </verify>
            <done>Web dashboard displays project info and allows execution</done>
        </task>
    </phase>
</phases>
```

## Task Structure Schema

Each `<task>` must contain:
- **id:** Unique identifier (phase.task format)
- **name:** Clear, actionable task name
- **files:** Specific files to create/modify
- **action:** Detailed implementation instructions
- **verify:** Command to verify task completion
- **done:** Acceptance criteria

## Execution Rules

1. **Sequential within phases** - Complete tasks in order within each phase
2. **Parallel between phases** - Independent phases can run concurrently
3. **Verify before proceeding** - Each task must pass verification
4. **Update STATE.md** - Log progress after each task
5. **Atomic commits** - One commit per completed task
