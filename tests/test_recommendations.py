"""Tests for the deterministic recommendation engine."""

import pytest

from sago.models.execution import ExecutionHistory, ExecutionRecord, VerifierResult
from sago.models.plan import Phase, Plan, Task
from sago.models.state import ProjectState, TaskState, TaskStatus
from sago.recommendations import RecommendationEngine, RecommendationType


@pytest.fixture
def engine() -> RecommendationEngine:
    return RecommendationEngine()


def _task(
    id: str,
    files: list[str] | None = None,
    verify: str = "pytest",
) -> Task:
    return Task(
        id=id,
        name=f"Task {id}",
        files=files if files is not None else ["file.py"],
        action="Do something",
        verify=verify,
        done="Done",
    )


def _plan(*phases: Phase) -> Plan:
    return Plan(phases=list(phases))


def _phase(name: str, *tasks: Task) -> Phase:
    return Phase(name=name, description="", tasks=list(tasks))


def _state(*task_states: TaskState) -> ProjectState:
    return ProjectState(task_states=list(task_states))


def _ts(task_id: str, status: TaskStatus) -> TaskState:
    return TaskState(task_id=task_id, status=status)


def _fail_record(task_id: str, attempt: int = 1) -> ExecutionRecord:
    return ExecutionRecord(
        task_id=task_id,
        attempt=attempt,
        verifier_result=VerifierResult(
            task_id=task_id, command="pytest", exit_code=1, stderr="fail"
        ),
    )


# --- Tests ---


class TestRepeatedFailure:
    def test_no_history(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1")))
        recs = engine.evaluate(plan, ProjectState())
        assert not any(r.type == RecommendationType.WARN_REPEATED_FAILURE for r in recs)

    def test_single_failure_no_warning(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1")))
        history = ExecutionHistory(records=[_fail_record("1.1")])
        recs = engine.evaluate(plan, ProjectState(), history)
        assert not any(r.type == RecommendationType.WARN_REPEATED_FAILURE for r in recs)

    def test_repeated_failure_warns(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1")))
        history = ExecutionHistory(records=[_fail_record("1.1", 1), _fail_record("1.1", 2)])
        recs = engine.evaluate(plan, ProjectState(), history)
        repeated = [r for r in recs if r.type == RecommendationType.WARN_REPEATED_FAILURE]
        assert len(repeated) == 1
        assert repeated[0].task_id == "1.1"


class TestSuggestReplan:
    def test_no_failures(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1"), _task("1.2"), _task("1.3")))
        state = _state()
        recs = engine.evaluate(plan, state)
        assert not any(r.type == RecommendationType.SUGGEST_REPLAN for r in recs)

    def test_above_threshold(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1"), _task("1.2"), _task("1.3")))
        state = _state(
            _ts("1.1", TaskStatus.FAILED),
            _ts("1.2", TaskStatus.FAILED),
            _ts("1.3", TaskStatus.PENDING),
        )
        recs = engine.evaluate(plan, state)
        assert any(r.type == RecommendationType.SUGGEST_REPLAN for r in recs)

    def test_below_threshold(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1"), _task("1.2"), _task("1.3"), _task("1.4")))
        state = _state(_ts("1.1", TaskStatus.FAILED))
        recs = engine.evaluate(plan, state)
        assert not any(r.type == RecommendationType.SUGGEST_REPLAN for r in recs)


class TestPhaseComplete:
    def test_phase_not_complete(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1"), _task("1.2")))
        state = _state(_ts("1.1", TaskStatus.DONE))
        recs = engine.evaluate(plan, state)
        assert not any(r.type == RecommendationType.PHASE_COMPLETE for r in recs)

    def test_phase_complete(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1"), _task("1.2")))
        state = _state(
            _ts("1.1", TaskStatus.DONE),
            _ts("1.2", TaskStatus.DONE),
        )
        recs = engine.evaluate(plan, state)
        assert any(r.type == RecommendationType.PHASE_COMPLETE for r in recs)


class TestSuggestReview:
    def test_suggests_when_phase_complete(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1")))
        state = _state(_ts("1.1", TaskStatus.DONE))
        recs = engine.evaluate(plan, state)
        assert any(r.type == RecommendationType.SUGGEST_REVIEW for r in recs)

    def test_no_suggest_when_incomplete(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1"), _task("1.2")))
        state = _state(_ts("1.1", TaskStatus.DONE))
        recs = engine.evaluate(plan, state)
        assert not any(r.type == RecommendationType.SUGGEST_REVIEW for r in recs)


class TestInvalidVerify:
    def test_empty_verify(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1", verify="")))
        recs = engine.evaluate(plan, ProjectState())
        assert any(r.type == RecommendationType.WARN_INVALID_VERIFY for r in recs)

    def test_true_verify(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1", verify="true")))
        recs = engine.evaluate(plan, ProjectState())
        assert any(r.type == RecommendationType.WARN_INVALID_VERIFY for r in recs)

    def test_echo_verify(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1", verify="echo")))
        recs = engine.evaluate(plan, ProjectState())
        assert any(r.type == RecommendationType.WARN_INVALID_VERIFY for r in recs)

    def test_real_verify(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1", verify="pytest tests/")))
        recs = engine.evaluate(plan, ProjectState())
        assert not any(r.type == RecommendationType.WARN_INVALID_VERIFY for r in recs)


class TestMissingTests:
    def test_py_files_without_pytest(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1", files=["app.py"], verify="python -c 'print(1)'")))
        recs = engine.evaluate(plan, ProjectState())
        assert any(r.type == RecommendationType.WARN_MISSING_TESTS for r in recs)

    def test_py_files_with_pytest(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1", files=["app.py"], verify="pytest tests/")))
        recs = engine.evaluate(plan, ProjectState())
        assert not any(r.type == RecommendationType.WARN_MISSING_TESTS for r in recs)

    def test_non_py_files(self, engine: RecommendationEngine) -> None:
        plan = _plan(
            _phase("P1", _task("1.1", files=["config.yaml"], verify="test -f config.yaml"))
        )
        recs = engine.evaluate(plan, ProjectState())
        assert not any(r.type == RecommendationType.WARN_MISSING_TESTS for r in recs)


class TestScopeDrift:
    def test_no_drift(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1")))
        state = _state(_ts("1.1", TaskStatus.DONE))
        recs = engine.evaluate(plan, state)
        assert not any(r.type == RecommendationType.WARN_SCOPE_DRIFT for r in recs)

    def test_drift_detected(self, engine: RecommendationEngine) -> None:
        plan = _plan(_phase("P1", _task("1.1")))
        state = _state(
            _ts("1.1", TaskStatus.DONE),
            _ts("99.99", TaskStatus.DONE),  # not in plan
        )
        recs = engine.evaluate(plan, state)
        drift = [r for r in recs if r.type == RecommendationType.WARN_SCOPE_DRIFT]
        assert len(drift) == 1
        assert drift[0].task_id == "99.99"


class TestIntegration:
    def test_multiple_recommendations(self, engine: RecommendationEngine) -> None:
        """Test that multiple rules fire simultaneously."""
        plan = _plan(
            _phase("P1", _task("1.1", verify="true"), _task("1.2", verify="")),
        )
        state = _state(
            _ts("1.1", TaskStatus.DONE),
            _ts("1.2", TaskStatus.DONE),
        )
        recs = engine.evaluate(plan, state)

        types = {r.type for r in recs}
        assert RecommendationType.PHASE_COMPLETE in types
        assert RecommendationType.SUGGEST_REVIEW in types
        assert RecommendationType.WARN_INVALID_VERIFY in types

    def test_empty_everything(self, engine: RecommendationEngine) -> None:
        plan = _plan()
        state = ProjectState()
        recs = engine.evaluate(plan, state)
        assert recs == []
