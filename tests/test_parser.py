from pathlib import Path

import pytest

from sago.core.parser import MarkdownParser, Phase, ResumePoint, Task


@pytest.fixture
def parser() -> MarkdownParser:
    return MarkdownParser()


def test_parse_xml_tasks(parser: MarkdownParser) -> None:
    content = """
# PLAN.md

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
                Create project structure with modern Python packaging.
                Set up dependencies.
            </action>
            <verify>
                python -c "import myproject"
            </verify>
            <done>Project imports successfully</done>
        </task>

        <task id="1.2">
            <name>Add Configuration</name>
            <files>src/config.py</files>
            <action>Create configuration management.</action>
            <verify>pytest tests/test_config.py</verify>
            <done>Config loads correctly</done>
        </task>
    </phase>

    <phase name="Phase 2: Features">
        <description>Implement core features</description>

        <task id="2.1">
            <name>Build CLI</name>
            <files>src/cli.py</files>
            <action>Create Typer CLI application.</action>
            <verify>cli --help</verify>
            <done>CLI works</done>
        </task>
    </phase>
</phases>
```
"""

    phases = parser.parse_xml_tasks(content)

    assert len(phases) == 2
    assert phases[0].name == "Phase 1: Foundation"
    assert phases[0].description == "Set up project structure"
    assert len(phases[0].tasks) == 2

    task1 = phases[0].tasks[0]
    assert task1.id == "1.1"
    assert task1.name == "Initialize Python Project"
    assert len(task1.files) == 2
    assert "pyproject.toml" in task1.files
    assert task1.verify == 'python -c "import myproject"'
    assert task1.phase_name == "Phase 1: Foundation"


def test_parse_xml_tasks_no_xml(parser: MarkdownParser) -> None:
    """Test that parser raises error when no XML found."""
    content = "# PLAN.md\n\nNo XML here!"

    with pytest.raises(ValueError, match="No XML task block found"):
        parser.parse_xml_tasks(content)


def test_parse_xml_tasks_invalid_xml(parser: MarkdownParser) -> None:
    content = "```xml\n<phases><phase>Missing closing tag\n```"

    with pytest.raises(ValueError, match="Invalid XML"):
        parser.parse_xml_tasks(content)


def test_parse_requirements(parser: MarkdownParser) -> None:
    """Test parsing requirements from REQUIREMENTS.md."""
    content = """
## REQUIREMENTS.md

### V1 Requirements (MVP)
* [ ] **REQ-1:** User can initialize a new project via CLI
* [x] **REQ-2:** System blocks youtube.com via hosts injection
* [ ] **REQ-3:** AI Agent parses PROJECT.md

### V2 Requirements (Post-Launch)
* [ ] **REQ-4:** Web dashboard for visualizing progress
"""

    requirements = parser.parse_requirements(content)

    assert len(requirements) == 4

    assert requirements[0].id == "REQ-1"
    assert requirements[0].completed is False
    assert requirements[0].version == "V1"
    assert "initialize" in requirements[0].description

    assert requirements[1].id == "REQ-2"
    assert requirements[1].completed is True

    assert requirements[3].version == "V2"


def test_parse_roadmap(parser: MarkdownParser) -> None:
    """Test parsing milestones from ROADMAP.md."""
    content = """
# ROADMAP.md

### Phase 1: The Foundation
* [x] **Milestone 1.1:** Repo setup and CI/CD pipelines
* [ ] **Milestone 1.2:** Implement the HostFileBlocker class
* [ ] **Milestone 1.3:** Build the PlannerAgent stub

### Phase 2: The Brain
* [ ] **Milestone 2.1:** Integrate litellm for model orchestration
"""

    milestones = parser.parse_roadmap(content)

    assert len(milestones) == 4

    assert milestones[0].id == "Milestone 1.1"
    assert milestones[0].phase == "Phase 1: The Foundation"
    assert milestones[0].completed is True

    assert milestones[1].id == "Milestone 1.2"
    assert milestones[1].completed is False

    assert milestones[3].phase == "Phase 2: The Brain"


def test_parse_state(parser: MarkdownParser) -> None:
    content = """
## STATE.md

### Current Context
* **Active Phase:** Phase 1, Milestone 1.2
* **Current Task:** Debugging the decorator in Windows

### Decisions Log
* **2023-10-27:** Decided to use Pydantic for validation
* **2023-10-28:** Switched from argparse to Typer

### Known Blockers
* Windows UAC prompt is not triggering correctly
"""

    state = parser.parse_state(content)

    assert "Phase 1" in state["active_phase"]
    assert "Debugging" in state["current_task"]
    assert len(state["decisions"]) == 2
    assert "Pydantic" in state["decisions"][0]
    assert len(state["blockers"]) == 1
    assert "UAC" in state["blockers"][0]


def test_parse_plan_file(parser: MarkdownParser, tmp_path: Path) -> None:
    """Test parsing PLAN.md file."""
    plan_file = tmp_path / "PLAN.md"
    plan_file.write_text(
        """
```xml
<phases>
    <phase name="Test Phase">
        <description>Test description</description>
        <task id="1">
            <name>Test Task</name>
            <files>test.py</files>
            <action>Test action</action>
            <verify>pytest</verify>
            <done>Tests pass</done>
        </task>
    </phase>
</phases>
```
"""
    )

    phases = parser.parse_plan_file(plan_file)

    assert len(phases) == 1
    assert phases[0].name == "Test Phase"
    assert len(phases[0].tasks) == 1


def test_task_to_dict() -> None:
    """Test converting Task to dictionary."""
    task = Task(
        id="1.1",
        name="Test Task",
        files=["test.py"],
        action="Do something",
        verify="pytest",
        done="Tests pass",
        phase_name="Phase 1",
        depends_on=["1.0"],
    )

    task_dict = task.to_dict()

    assert task_dict["id"] == "1.1"
    assert task_dict["name"] == "Test Task"
    assert task_dict["files"] == ["test.py"]
    assert task_dict["phase_name"] == "Phase 1"
    assert task_dict["depends_on"] == ["1.0"]


def test_parse_xml_tasks_with_depends_on(parser: MarkdownParser) -> None:
    """Test that depends_on attributes are parsed correctly."""
    content = """
```xml
<phases>
    <phase name="Phase 1: Setup">
        <description>Setup</description>
        <task id="1.1">
            <name>Init</name>
            <files>init.py</files>
            <action>Initialize</action>
            <verify>true</verify>
            <done>Done</done>
        </task>
        <task id="1.2" depends_on="1.1">
            <name>Config</name>
            <files>config.py</files>
            <action>Add config</action>
            <verify>true</verify>
            <done>Done</done>
        </task>
    </phase>
    <phase name="Phase 2: Features">
        <description>Features</description>
        <task id="2.1" depends_on="1.1, 1.2">
            <name>CLI</name>
            <files>cli.py</files>
            <action>Build CLI</action>
            <verify>true</verify>
            <done>Done</done>
        </task>
    </phase>
</phases>
```
"""
    phases = parser.parse_xml_tasks(content)

    assert phases[0].tasks[0].depends_on == []
    assert phases[0].tasks[1].depends_on == ["1.1"]
    assert phases[1].tasks[0].depends_on == ["1.1", "1.2"]


def test_parse_xml_tasks_no_depends_on(parser: MarkdownParser) -> None:
    """Test that tasks without depends_on get empty list (backward compatible)."""
    content = """
```xml
<phases>
    <phase name="Phase 1">
        <description>Desc</description>
        <task id="1.1">
            <name>Task</name>
            <files>f.py</files>
            <action>Do something</action>
            <verify>true</verify>
            <done>Done</done>
        </task>
    </phase>
</phases>
```
"""
    phases = parser.parse_xml_tasks(content)
    assert phases[0].tasks[0].depends_on == []


def test_parse_dependencies(parser: MarkdownParser) -> None:
    """Test parsing dependencies from PLAN.md XML."""
    content = """
# PLAN.md

```xml
<phases>
    <dependencies>
        <package>flask>=2.0</package>
        <package>requests>=2.28</package>
        <package>pydantic>=2.0</package>
    </dependencies>

    <phase name="Phase 1: Foundation">
        <description>Set up project</description>
        <task id="1.1">
            <name>Setup</name>
            <files>setup.py</files>
            <action>Create setup</action>
            <verify>python -c "print('ok')"</verify>
            <done>Done</done>
        </task>
    </phase>
</phases>
```
"""
    deps = parser.parse_dependencies(content)
    assert deps == ["flask>=2.0", "requests>=2.28", "pydantic>=2.0"]


def test_parse_dependencies_no_deps(parser: MarkdownParser) -> None:
    """Test that missing <dependencies> returns empty list."""
    content = """
```xml
<phases>
    <phase name="Phase 1">
        <description>Desc</description>
        <task id="1.1">
            <name>Task</name>
            <files>f.py</files>
            <action>Do something</action>
            <verify>true</verify>
            <done>Done</done>
        </task>
    </phase>
</phases>
```
"""
    deps = parser.parse_dependencies(content)
    assert deps == []


def test_parse_dependencies_empty_deps(parser: MarkdownParser) -> None:
    """Test that empty <dependencies> returns empty list."""
    content = """
```xml
<phases>
    <dependencies></dependencies>
    <phase name="Phase 1">
        <description>Desc</description>
        <task id="1.1">
            <name>Task</name>
            <files>f.py</files>
            <action>Do something</action>
            <verify>true</verify>
            <done>Done</done>
        </task>
    </phase>
</phases>
```
"""
    deps = parser.parse_dependencies(content)
    assert deps == []


def test_parse_dependencies_no_xml(parser: MarkdownParser) -> None:
    """Test that non-XML content returns empty list."""
    deps = parser.parse_dependencies("# No XML here")
    assert deps == []


def test_phase_to_dict() -> None:
    """Test converting Phase to dictionary."""
    task = Task(id="1", name="Task", files=[], action="", verify="", done="", phase_name="")
    phase = Phase(name="Phase 1", description="Description", tasks=[task])

    phase_dict = phase.to_dict()

    assert phase_dict["name"] == "Phase 1"
    assert phase_dict["description"] == "Description"
    assert len(phase_dict["tasks"]) == 1


def test_parse_resume_point_success(parser: MarkdownParser) -> None:
    """Test parsing resume point after a successful task."""
    content = """
## Resume Point

* **Last Completed:** 1.2: Add Configuration
* **Next Task:** 2.1: Build CLI
* **Next Action:** Create Typer CLI application
* **Failure Reason:** None
* **Checkpoint:** sago-checkpoint-1.2

## Completed Tasks
"""
    rp = parser.parse_resume_point(content)
    assert rp is not None
    assert rp.last_completed == "1.2: Add Configuration"
    assert rp.next_task == "2.1: Build CLI"
    assert rp.next_action == "Create Typer CLI application"
    assert rp.failure_reason == "None"
    assert rp.checkpoint == "sago-checkpoint-1.2"


def test_parse_resume_point_failure(parser: MarkdownParser) -> None:
    """Test parsing resume point after a failed task."""
    content = """
## Resume Point

* **Last Completed:** 1.1: Initialize Project
* **Next Task:** 1.2: Add Configuration (retry)
* **Next Action:** Fix config loading for nested keys
* **Failure Reason:** pytest tests/test_config.py exited 1 — KeyError on nested.key
* **Checkpoint:** sago-checkpoint-1.1

## Completed Tasks
"""
    rp = parser.parse_resume_point(content)
    assert rp is not None
    assert rp.next_task == "1.2: Add Configuration (retry)"
    assert "KeyError" in rp.failure_reason
    assert rp.checkpoint == "sago-checkpoint-1.1"


def test_parse_resume_point_all_none(parser: MarkdownParser) -> None:
    """Test that all-None fields returns None."""
    content = """
## Resume Point

* **Last Completed:** None
* **Next Task:** None
* **Next Action:** None
* **Failure Reason:** None
* **Checkpoint:** None

## Completed Tasks
"""
    assert parser.parse_resume_point(content) is None


def test_parse_resume_point_missing_section(parser: MarkdownParser) -> None:
    """Test that missing section returns None."""
    content = """
## Current Context

* **Active Phase:** Phase 1

## Completed Tasks
"""
    assert parser.parse_resume_point(content) is None


def test_resume_point_to_dict() -> None:
    """Test ResumePoint.to_dict()."""
    rp = ResumePoint(
        last_completed="1.1: Setup",
        next_task="1.2: Config",
        next_action="Create config module",
        failure_reason="None",
        checkpoint="sago-checkpoint-1.1",
    )
    d = rp.to_dict()
    assert d["last_completed"] == "1.1: Setup"
    assert d["next_task"] == "1.2: Config"
    assert d["next_action"] == "Create config module"
    assert d["failure_reason"] == "None"
    assert d["checkpoint"] == "sago-checkpoint-1.1"


def test_parse_state_includes_resume_point(parser: MarkdownParser) -> None:
    """Test that parse_state includes resume_point key."""
    content = """
### Current Context
* **Active Phase:** Phase 1
* **Current Task:** 1.2

## Resume Point

* **Last Completed:** 1.1: Setup
* **Next Task:** 1.2: Config
* **Next Action:** Create config
* **Failure Reason:** None
* **Checkpoint:** sago-checkpoint-1.1
"""
    state = parser.parse_state(content)
    assert "resume_point" in state
    assert state["resume_point"] is not None
    assert state["resume_point"].last_completed == "1.1: Setup"


def test_parse_state_resume_point_none_when_missing(parser: MarkdownParser) -> None:
    """Test that parse_state returns None for resume_point when section missing."""
    content = """
### Current Context
* **Active Phase:** Phase 1
* **Current Task:** 1.1
"""
    state = parser.parse_state(content)
    assert state["resume_point"] is None


# --- parse_state_tasks tests ---

def _make_phases() -> list[Phase]:
    """Helper to create test phases for parse_state_tasks."""
    return [
        Phase(
            name="Phase 1: Foundation",
            description="Setup",
            tasks=[
                Task(id="1.1", name="Create config", files=["config.py"],
                     action="Create config", verify="python -c 'import config'",
                     done="Config exists", phase_name="Phase 1: Foundation"),
                Task(id="1.2", name="Create main", files=["main.py"],
                     action="Create main", verify="python -c 'import main'",
                     done="Main exists", phase_name="Phase 1: Foundation"),
            ],
        ),
        Phase(
            name="Phase 2: Features",
            description="Build features",
            tasks=[
                Task(id="2.1", name="Build CLI", files=["cli.py"],
                     action="Create CLI", verify="cli --help",
                     done="CLI works", phase_name="Phase 2: Features"),
            ],
        ),
    ]


def test_parse_state_tasks_all_pending(parser: MarkdownParser) -> None:
    """All tasks are pending when STATE.md has no completed/failed markers."""
    content = "# STATE.md\n\n## Current Context\n"
    phases = _make_phases()

    results = parser.parse_state_tasks(content, phases)

    assert len(results) == 3
    assert all(r["status"] == "pending" for r in results)
    assert results[0]["id"] == "1.1"
    assert results[0]["phase_name"] == "Phase 1: Foundation"


def test_parse_state_tasks_done_and_failed(parser: MarkdownParser) -> None:
    """Correctly identifies done and failed tasks."""
    content = """\
## Completed Tasks
[✓] 1.1: Create config — Config exists
[✗] 1.2: Create main — ImportError
"""
    phases = _make_phases()

    results = parser.parse_state_tasks(content, phases)

    by_id = {r["id"]: r for r in results}
    assert by_id["1.1"]["status"] == "done"
    assert by_id["1.2"]["status"] == "failed"
    assert by_id["2.1"]["status"] == "pending"


def test_parse_state_tasks_all_done(parser: MarkdownParser) -> None:
    """All tasks done when all are marked with checkmark."""
    content = """\
[✓] 1.1: Create config
[✓] 1.2: Create main
[✓] 2.1: Build CLI
"""
    phases = _make_phases()

    results = parser.parse_state_tasks(content, phases)

    assert all(r["status"] == "done" for r in results)


def test_parse_state_tasks_preserves_phase_name(parser: MarkdownParser) -> None:
    """Each task result includes the correct phase_name."""
    content = "[✓] 2.1: Build CLI\n"
    phases = _make_phases()

    results = parser.parse_state_tasks(content, phases)

    cli_result = next(r for r in results if r["id"] == "2.1")
    assert cli_result["phase_name"] == "Phase 2: Features"
    assert cli_result["status"] == "done"
