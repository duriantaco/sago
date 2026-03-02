"""Shared fixtures for sago tests."""

from pathlib import Path

import pytest

SAMPLE_XML = """\
<phases>
    <phase name="Phase 1: Foundation">
        <description>Set up project</description>

        <task id="1.1">
            <name>Create config</name>
            <files>config.py</files>
            <action>Create configuration module</action>
            <verify>python -c "import config"</verify>
            <done>Config module exists</done>
        </task>

        <task id="1.2" depends_on="1.1">
            <name>Create main</name>
            <files>main.py</files>
            <action>Create main module</action>
            <verify>python -c "import main"</verify>
            <done>Main module exists</done>
        </task>
    </phase>
</phases>"""

SAMPLE_PLAN = f"""\
# Test Plan

> **CRITICAL COMPONENT:** This file uses a specific XML schema.

```xml
{SAMPLE_XML}
```
"""

SAMPLE_STATE = """\
# Test State

## Current Context

* **Active Phase:** Phase 1: Foundation
* **Current Task:** 1.2: Create main

## Resume Point

* **Last Completed:** 1.1: Create config
* **Next Task:** 1.2: Create main
* **Next Action:** Create main module
* **Failure Reason:** None
* **Checkpoint:** sago-checkpoint-1.1

## Completed Tasks
[✓] 1.1: Create config — Config module exists
"""


@pytest.fixture
def sago_project(tmp_path: Path) -> Path:
    """Create a minimal sago project directory with all required files."""
    (tmp_path / "PROJECT.md").write_text(
        "# Test Project\n\n## Project Vision\nA test project.\n\n"
        "## Tech Stack & Constraints\n* Python 3.12\n\n"
        "## Core Architecture\nSingle module.\n"
    )
    (tmp_path / "REQUIREMENTS.md").write_text(
        "# Test Requirements\n\n## V1 Requirements (MVP)\n\n"
        "* [ ] **REQ-1:** Create a config module\n"
        "* [ ] **REQ-2:** Create a main module\n"
    )
    (tmp_path / "STATE.md").write_text(SAMPLE_STATE)
    (tmp_path / "IMPORTANT.md").write_text("# Important\nNothing yet.\n")
    (tmp_path / "CLAUDE.md").write_text("# CLAUDE.md\nTest agent instructions.\n")
    (tmp_path / ".planning").mkdir()
    return tmp_path


@pytest.fixture
def sago_project_with_plan(sago_project: Path) -> Path:
    """Sago project that also has a PLAN.md."""
    (sago_project / "PLAN.md").write_text(SAMPLE_PLAN)
    return sago_project
