"""Deterministic, state-grounded recommendation engine.

All rules are based on typed state — no LLM calls, no vague intuition.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from sago.models.execution import ExecutionHistory
from sago.models.plan import Plan
from sago.models.state import ProjectState


class RecommendationType(StrEnum):
    """Type of recommendation."""

    SUGGEST_REPLAN = "suggest_replan"
    WARN_REPEATED_FAILURE = "warn_repeated_failure"
    WARN_SCOPE_DRIFT = "warn_scope_drift"
    SUGGEST_REVIEW = "suggest_review"
    WARN_INVALID_VERIFY = "warn_invalid_verify"
    WARN_MISSING_TESTS = "warn_missing_tests"
    PHASE_COMPLETE = "phase_complete"


class Recommendation(BaseModel):
    """A single actionable recommendation."""

    type: RecommendationType
    message: str
    task_id: str | None = None
    phase_name: str | None = None
    dismissible: bool = True


class RecommendationEngine:
    """Evaluates plan + state + execution history to produce grounded recommendations."""

    def evaluate(
        self,
        plan: Plan,
        state: ProjectState,
        execution_history: ExecutionHistory | None = None,
    ) -> list[Recommendation]:
        """Run all recommendation rules and return results."""
        recommendations: list[Recommendation] = []
        recommendations.extend(self._check_repeated_failures(execution_history))
        recommendations.extend(self._check_suggest_replan(plan, state))
        recommendations.extend(self._check_phase_complete(plan, state))
        recommendations.extend(self._check_suggest_review(plan, state))
        recommendations.extend(self._check_invalid_verify(plan))
        recommendations.extend(self._check_missing_tests(plan))
        recommendations.extend(self._check_scope_drift(plan, state))
        return recommendations

    def _check_repeated_failures(
        self, execution_history: ExecutionHistory | None
    ) -> list[Recommendation]:
        if execution_history is None:
            return []
        repeated = execution_history.repeated_failures(threshold=2)
        return [
            Recommendation(
                type=RecommendationType.WARN_REPEATED_FAILURE,
                message=f"Task {tid} has failed multiple times. Consider replanning this task.",
                task_id=tid,
            )
            for tid in repeated
        ]

    def _check_suggest_replan(self, plan: Plan, state: ProjectState) -> list[Recommendation]:
        """Suggest replan if > 30% of tasks in any phase have failed."""
        recommendations = []
        failed_ids = state.failed_task_ids()

        for phase in plan.phases:
            if not phase.tasks:
                continue
            failed_count = sum(1 for t in phase.tasks if t.id in failed_ids)
            if failed_count / len(phase.tasks) > 0.3:
                recommendations.append(
                    Recommendation(
                        type=RecommendationType.SUGGEST_REPLAN,
                        message=(
                            f"{failed_count}/{len(phase.tasks)} tasks failed in {phase.name}. "
                            f"Consider running `sago replan`."
                        ),
                        phase_name=phase.name,
                    )
                )
        return recommendations

    def _check_phase_complete(self, plan: Plan, state: ProjectState) -> list[Recommendation]:
        """Notify when all tasks in a phase are done."""
        recommendations = []
        completed_ids = state.completed_task_ids()

        for phase in plan.phases:
            if not phase.tasks:
                continue
            if all(t.id in completed_ids for t in phase.tasks):
                recommendations.append(
                    Recommendation(
                        type=RecommendationType.PHASE_COMPLETE,
                        message=f"{phase.name} is complete.",
                        phase_name=phase.name,
                    )
                )
        return recommendations

    def _check_suggest_review(self, plan: Plan, state: ProjectState) -> list[Recommendation]:
        """Suggest review if a phase is complete (review availability is a heuristic)."""
        recommendations = []
        completed_ids = state.completed_task_ids()

        for phase in plan.phases:
            if not phase.tasks:
                continue
            if all(t.id in completed_ids for t in phase.tasks):
                recommendations.append(
                    Recommendation(
                        type=RecommendationType.SUGGEST_REVIEW,
                        message=(
                            f"{phase.name} is complete. "
                            f"Run `sago replan` to review and plan next steps."
                        ),
                        phase_name=phase.name,
                    )
                )
        return recommendations

    def _check_invalid_verify(self, plan: Plan) -> list[Recommendation]:
        """Warn about tasks with no-op verification commands."""
        recommendations = []
        no_op_commands = {"echo", "true", "echo ok", "echo 'ok'", 'echo "ok"', "exit 0"}

        for task in plan.all_tasks():
            verify = task.verify.strip().lower()
            if not verify or verify in no_op_commands:
                recommendations.append(
                    Recommendation(
                        type=RecommendationType.WARN_INVALID_VERIFY,
                        message=f"Task {task.id} has no meaningful verification command.",
                        task_id=task.id,
                    )
                )
        return recommendations

    def _check_missing_tests(self, plan: Plan) -> list[Recommendation]:
        """Warn if a task creates .py files but verify doesn't run pytest."""
        recommendations = []
        for task in plan.all_tasks():
            has_py_files = any(f.endswith(".py") for f in task.files)
            runs_pytest = "pytest" in task.verify.lower()
            if has_py_files and not runs_pytest:
                recommendations.append(
                    Recommendation(
                        type=RecommendationType.WARN_MISSING_TESTS,
                        message=f"Task {task.id} creates Python files but verify doesn't run pytest.",
                        task_id=task.id,
                    )
                )
        return recommendations

    def _check_scope_drift(self, plan: Plan, state: ProjectState) -> list[Recommendation]:
        """Warn if state references task IDs not in the plan."""
        recommendations = []
        plan_ids = plan.task_ids()

        for ts in state.task_states:
            if ts.task_id not in plan_ids:
                recommendations.append(
                    Recommendation(
                        type=RecommendationType.WARN_SCOPE_DRIFT,
                        message=(
                            f"State references task {ts.task_id} which is not in the plan. "
                            f"State may be stale."
                        ),
                        task_id=ts.task_id,
                    )
                )
        return recommendations
