"""Tests for Pydantic models: plan, state, and execution."""

import json

import pytest

from sago.models import (
    Dependency,
    ExecutionHistory,
    ExecutionRecord,
    FailureCategory,
    Milestone,
    Phase,
    Plan,
    ProjectState,
    Requirement,
    Requirements,
    ResumePoint,
    ReviewPrompt,
    Roadmap,
    Task,
    TaskState,
    TaskStatus,
    VerifierResult,
    classify_failure,
)

# --- Plan models ---


class TestTask:
    def test_create(self) -> None:
        task = Task(
            id="1.1",
            name="Setup",
            files=["setup.py"],
            action="Create setup",
            verify="pytest",
            done="Tests pass",
        )
        assert task.id == "1.1"
        assert task.depends_on == []
        assert task.phase_name == ""

    def test_to_dict(self) -> None:
        task = Task(
            id="1.1",
            name="Setup",
            files=["a.py", "b.py"],
            action="Do it",
            verify="pytest",
            done="Done",
            phase_name="Phase 1",
            depends_on=["1.0"],
        )
        d = task.to_dict()
        assert d["id"] == "1.1"
        assert d["files"] == ["a.py", "b.py"]
        assert d["depends_on"] == ["1.0"]
        assert d["phase_name"] == "Phase 1"


class TestPhase:
    def test_create(self) -> None:
        task = Task(id="1", name="T", files=[], action="", verify="", done="")
        phase = Phase(name="Phase 1", description="Desc", tasks=[task])
        assert phase.name == "Phase 1"
        assert len(phase.tasks) == 1

    def test_to_dict(self) -> None:
        task = Task(id="1", name="T", files=[], action="", verify="", done="")
        phase = Phase(name="Phase 1", description="Desc", tasks=[task])
        d = phase.to_dict()
        assert d["name"] == "Phase 1"
        assert len(d["tasks"]) == 1


class TestPlan:
    @pytest.fixture
    def sample_plan(self) -> Plan:
        return Plan(
            phases=[
                Phase(
                    name="Phase 1",
                    description="Foundation",
                    tasks=[
                        Task(
                            id="1.1",
                            name="Init",
                            files=["init.py"],
                            action="Init project",
                            verify="python -c 'print(1)'",
                            done="Done",
                            phase_name="Phase 1",
                        ),
                        Task(
                            id="1.2",
                            name="Config",
                            files=["config.py"],
                            action="Add config",
                            verify="pytest",
                            done="Done",
                            phase_name="Phase 1",
                            depends_on=["1.1"],
                        ),
                    ],
                ),
                Phase(
                    name="Phase 2",
                    description="Features",
                    tasks=[
                        Task(
                            id="2.1",
                            name="CLI",
                            files=["cli.py"],
                            action="Build CLI",
                            verify="cli --help",
                            done="Done",
                            phase_name="Phase 2",
                            depends_on=["1.1", "1.2"],
                        ),
                    ],
                ),
            ],
            dependencies=[Dependency(package="flask>=2.0"), Dependency(package="requests")],
            review_prompt=ReviewPrompt(content="Review carefully"),
        )

    def test_all_tasks(self, sample_plan: Plan) -> None:
        assert len(sample_plan.all_tasks()) == 3

    def test_get_task(self, sample_plan: Plan) -> None:
        task = sample_plan.get_task("1.2")
        assert task is not None
        assert task.name == "Config"
        assert sample_plan.get_task("99") is None

    def test_task_ids(self, sample_plan: Plan) -> None:
        assert sample_plan.task_ids() == {"1.1", "1.2", "2.1"}

    def test_dependency_graph(self, sample_plan: Plan) -> None:
        graph = sample_plan.dependency_graph()
        assert graph["1.1"] == []
        assert graph["1.2"] == ["1.1"]
        assert graph["2.1"] == ["1.1", "1.2"]

    def test_dependency_packages(self, sample_plan: Plan) -> None:
        assert sample_plan.dependency_packages() == ["flask>=2.0", "requests"]

    def test_json_roundtrip(self, sample_plan: Plan) -> None:
        json_str = sample_plan.to_json()
        restored = Plan.from_json(json_str)
        assert restored.task_ids() == sample_plan.task_ids()
        assert restored.dependency_packages() == sample_plan.dependency_packages()
        assert restored.review_prompt is not None
        assert restored.review_prompt.content == "Review carefully"

    def test_to_xml(self, sample_plan: Plan) -> None:
        xml = sample_plan.to_xml()
        assert "<phases>" in xml
        assert "</phases>" in xml
        assert 'name="Phase 1"' in xml
        assert 'id="1.1"' in xml
        assert 'depends_on="1.1"' in xml
        assert "<package>flask&gt;=2.0</package>" in xml or "flask>=2.0" in xml.replace("&gt;", ">")
        assert "<review>" in xml

    def test_empty_plan(self) -> None:
        plan = Plan(phases=[])
        assert plan.all_tasks() == []
        assert plan.task_ids() == set()
        assert plan.dependency_graph() == {}


# --- State models ---


class TestTaskStatus:
    def test_enum_values(self) -> None:
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.DONE == "done"
        assert TaskStatus.FAILED == "failed"
        assert TaskStatus.SKIPPED == "skipped"


class TestProjectState:
    def test_task_id_helpers(self) -> None:
        state = ProjectState(
            task_states=[
                TaskState(task_id="1.1", status=TaskStatus.DONE),
                TaskState(task_id="1.2", status=TaskStatus.FAILED),
                TaskState(task_id="2.1", status=TaskStatus.PENDING),
                TaskState(task_id="2.2", status=TaskStatus.DONE),
            ]
        )
        assert state.completed_task_ids() == {"1.1", "2.2"}
        assert state.failed_task_ids() == {"1.2"}
        assert state.pending_task_ids() == {"2.1"}

    def test_json_roundtrip(self) -> None:
        state = ProjectState(
            active_phase="Phase 1",
            current_task="1.2",
            task_states=[TaskState(task_id="1.1", status=TaskStatus.DONE, note="OK")],
            decisions=["Used Pydantic"],
            blockers=["Windows compat"],
            resume_point=ResumePoint(
                last_completed="1.1",
                next_task="1.2",
                next_action="Add config",
                failure_reason="None",
                checkpoint="sago-1.1",
            ),
        )
        json_str = state.to_json()
        restored = ProjectState.from_json(json_str)
        assert restored.active_phase == "Phase 1"
        assert restored.completed_task_ids() == {"1.1"}
        assert restored.resume_point is not None
        assert restored.resume_point.next_task == "1.2"

    def test_empty_state(self) -> None:
        state = ProjectState()
        assert state.completed_task_ids() == set()
        assert state.failed_task_ids() == set()
        assert state.pending_task_ids() == set()


class TestResumePoint:
    def test_to_dict(self) -> None:
        rp = ResumePoint(
            last_completed="1.1: Setup",
            next_task="1.2: Config",
            next_action="Create config",
            failure_reason="None",
            checkpoint="sago-1.1",
        )
        d = rp.to_dict()
        assert d["last_completed"] == "1.1: Setup"
        assert d["checkpoint"] == "sago-1.1"


class TestRequirement:
    def test_to_dict(self) -> None:
        req = Requirement(id="REQ-1", description="Init project", completed=True, version="V2")
        d = req.to_dict()
        assert d["id"] == "REQ-1"
        assert d["completed"] is True
        assert d["version"] == "V2"


class TestMilestone:
    def test_to_dict(self) -> None:
        ms = Milestone(id="M1", phase="Phase 1", description="Setup", completed=False)
        d = ms.to_dict()
        assert d["id"] == "M1"
        assert d["phase"] == "Phase 1"


class TestRequirements:
    def test_create(self) -> None:
        reqs = Requirements(
            requirements=[
                Requirement(id="REQ-1", description="Test"),
                Requirement(id="REQ-2", description="Test2", completed=True),
            ]
        )
        assert len(reqs.requirements) == 2


class TestRoadmap:
    def test_create(self) -> None:
        rm = Roadmap(milestones=[Milestone(id="M1", phase="P1", description="D")])
        assert len(rm.milestones) == 1


# --- Execution models ---


class TestClassifyFailure:
    def test_syntax_error(self) -> None:
        assert classify_failure("SyntaxError: invalid syntax", 1) == FailureCategory.SYNTAX_ERROR

    def test_indentation_error(self) -> None:
        assert (
            classify_failure("IndentationError: unexpected indent", 1)
            == FailureCategory.SYNTAX_ERROR
        )

    def test_import_error(self) -> None:
        assert (
            classify_failure("ModuleNotFoundError: No module named 'kafka'", 1)
            == FailureCategory.IMPORT_ERROR
        )

    def test_import_error_generic(self) -> None:
        assert (
            classify_failure("ImportError: cannot import name 'foo'", 1)
            == FailureCategory.IMPORT_ERROR
        )

    def test_assertion_failure(self) -> None:
        assert (
            classify_failure("AssertionError: expected True", 1)
            == FailureCategory.ASSERTION_FAILURE
        )

    def test_assertion_pytest(self) -> None:
        assert (
            classify_failure("FAILED tests/test_foo.py::test_bar - assert 1 == 2", 1)
            == FailureCategory.ASSERTION_FAILURE
        )

    def test_environment_missing(self) -> None:
        assert (
            classify_failure("bash: docker: command not found", 127)
            == FailureCategory.ENVIRONMENT_MISSING
        )

    def test_timeout(self) -> None:
        assert classify_failure("TimeoutError: operation timed out", 1) == FailureCategory.TIMEOUT

    def test_timeout_timed_out(self) -> None:
        assert classify_failure("Process timed out after 30s", 1) == FailureCategory.TIMEOUT

    def test_runtime_error(self) -> None:
        assert (
            classify_failure("TypeError: unsupported operand", 1) == FailureCategory.RUNTIME_ERROR
        )

    def test_traceback(self) -> None:
        stderr = "Traceback (most recent call last):\n  File 'x.py'\nKeyError: 'foo'"
        assert classify_failure(stderr, 1) == FailureCategory.RUNTIME_ERROR

    def test_unknown(self) -> None:
        assert classify_failure("something weird happened", 1) == FailureCategory.UNKNOWN

    def test_exit_code_zero(self) -> None:
        assert classify_failure("SyntaxError: blah", 0) == FailureCategory.UNKNOWN


class TestExecutionHistory:
    def test_failures_for_task(self) -> None:
        history = ExecutionHistory(
            records=[
                ExecutionRecord(
                    task_id="1.1",
                    attempt=1,
                    verifier_result=VerifierResult(
                        task_id="1.1", command="pytest", exit_code=1, stderr="fail"
                    ),
                ),
                ExecutionRecord(
                    task_id="1.1",
                    attempt=2,
                    verifier_result=VerifierResult(task_id="1.1", command="pytest", exit_code=0),
                ),
                ExecutionRecord(
                    task_id="1.2",
                    attempt=1,
                    verifier_result=VerifierResult(
                        task_id="1.2", command="pytest", exit_code=1, stderr="fail"
                    ),
                ),
            ]
        )
        failures = history.failures_for_task("1.1")
        assert len(failures) == 1
        assert failures[0].attempt == 1

    def test_repeated_failures(self) -> None:
        history = ExecutionHistory(
            records=[
                ExecutionRecord(
                    task_id="1.1",
                    attempt=1,
                    verifier_result=VerifierResult(task_id="1.1", command="pytest", exit_code=1),
                ),
                ExecutionRecord(
                    task_id="1.1",
                    attempt=2,
                    verifier_result=VerifierResult(task_id="1.1", command="pytest", exit_code=1),
                ),
                ExecutionRecord(
                    task_id="1.2",
                    attempt=1,
                    verifier_result=VerifierResult(task_id="1.2", command="pytest", exit_code=1),
                ),
            ]
        )
        assert history.repeated_failures(threshold=2) == ["1.1"]
        assert sorted(history.repeated_failures(threshold=1)) == ["1.1", "1.2"]

    def test_json_roundtrip(self) -> None:
        history = ExecutionHistory(
            records=[
                ExecutionRecord(
                    task_id="1.1",
                    attempt=1,
                    verifier_result=VerifierResult(
                        task_id="1.1",
                        command="pytest",
                        exit_code=1,
                        stderr="ImportError",
                        failure_category=FailureCategory.IMPORT_ERROR,
                    ),
                    files_changed=["src/app.py"],
                ),
            ]
        )
        json_str = history.to_json()
        data = json.loads(json_str)
        assert data["records"][0]["task_id"] == "1.1"

        restored = ExecutionHistory.from_json(json_str)
        assert len(restored.records) == 1
        assert restored.records[0].verifier_result is not None
        assert restored.records[0].verifier_result.failure_category == FailureCategory.IMPORT_ERROR

    def test_empty_history(self) -> None:
        history = ExecutionHistory()
        assert history.failures_for_task("1.1") == []
        assert history.repeated_failures() == []
