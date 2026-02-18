import logging
from dataclasses import dataclass
from typing import Any

from sago.core.parser import Task

logger = logging.getLogger(__name__)


@dataclass
class CostEstimate:

    total_tasks: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_cost_usd: float
    estimated_duration_seconds: tuple[int, int]  # (min, max)
    model: str
    breakdown_by_phase: dict[str, dict[str, Any]]

    def __str__(self) -> str:
        """Format cost estimate as string."""
        min_time, max_time = self.estimated_duration_seconds
        min_minutes = min_time // 60
        max_minutes = max_time // 60

        lines = [
            "Cost Estimate:",
            "",
            f"Total Tasks: {self.total_tasks}",
            f"Estimated Tokens: {self.estimated_total_tokens:,}",
            f"  Input: {self.estimated_input_tokens:,}",
            f"  Output: {self.estimated_output_tokens:,}",
            f"Estimated Cost: ${self.estimated_cost_usd:.2f}",
            f"Estimated Time: {min_minutes}-{max_minutes} minutes",
            f"Model: {self.model}",
        ]

        if self.breakdown_by_phase:
            lines.append("")
            lines.append("Breakdown by Phase:")
            for phase_name, data in self.breakdown_by_phase.items():
                lines.append(
                    f"  {phase_name}: {data['tasks']} tasks, "
                    f"${data['cost']:.2f}, {data['time_min']}-{data['time_max']}min"
                )

        return "\n".join(lines)


class CostEstimator:

    MODEL_COSTS: dict[str, dict[str, float]] = {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4": {"input": 30.00, "output": 60.00},
        "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
        "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
        "claude-haiku-4-20250414": {"input": 0.80, "output": 4.00},
    }

    TOKEN_ESTIMATES: dict[str, dict[str, int]] = {
        "plan_generation": {"input": 2000, "output": 3000},
        "task_execution": {"input": 1500, "output": 800},
        "code_review": {"input": 800, "output": 200},
    }

    TIME_ESTIMATES: dict[str, tuple[int, int]] = {
        "plan_generation": (30, 60),
        "task_execution": (10, 30),
        "verification": (5, 15),
    }

    def __init__(self, model: str = "gpt-4o") -> None:
        """Initialize cost estimator.

        Args:
            model: LLM model name
        """
        self.model = model
        self.logger = logging.getLogger(self.__class__.__name__)

        # Get cost rates for model
        if model in self.MODEL_COSTS:
            self.cost_rates = self.MODEL_COSTS[model]
        else:
            self.logger.warning(f"Unknown model {model}, using gpt-4o pricing")
            self.cost_rates = self.MODEL_COSTS["gpt-4o"]

    def estimate_workflow(
        self,
        tasks: list[Task],
        generate_plan: bool = False,
        verify: bool = True,
    ) -> CostEstimate:

        total_input_tokens = 0
        total_output_tokens = 0
        min_time = 0
        max_time = 0

        if generate_plan:
            plan_tokens = self.TOKEN_ESTIMATES["plan_generation"]
            total_input_tokens += plan_tokens["input"]
            total_output_tokens += plan_tokens["output"]
            plan_time = self.TIME_ESTIMATES["plan_generation"]
            min_time += plan_time[0]
            max_time += plan_time[1]

        # Task execution cost
        for _task in tasks:
            task_tokens = self.TOKEN_ESTIMATES["task_execution"]
            total_input_tokens += task_tokens["input"]
            total_output_tokens += task_tokens["output"]

            exec_time = self.TIME_ESTIMATES["task_execution"]
            min_time += exec_time[0]
            max_time += exec_time[1]

            if verify:
                verify_time = self.TIME_ESTIMATES["verification"]
                min_time += verify_time[0]
                max_time += verify_time[1]

        input_cost = (total_input_tokens / 1_000_000) * self.cost_rates["input"]
        output_cost = (total_output_tokens / 1_000_000) * self.cost_rates["output"]
        total_cost = input_cost + output_cost

        breakdown = self._create_phase_breakdown(tasks, verify)

        return CostEstimate(
            total_tasks=len(tasks),
            estimated_input_tokens=total_input_tokens,
            estimated_output_tokens=total_output_tokens,
            estimated_total_tokens=total_input_tokens + total_output_tokens,
            estimated_cost_usd=total_cost,
            estimated_duration_seconds=(min_time, max_time),
            model=self.model,
            breakdown_by_phase=breakdown,
        )

    def _create_phase_breakdown(
        self, tasks: list[Task], verify: bool
    ) -> dict[str, dict[str, Any]]:

        breakdown: dict[str, dict[str, Any]] = {}

        phases: dict[str, list[Task]] = {}
        for task in tasks:
            phase_name = task.phase_name or "Unknown Phase"
            if phase_name not in phases:
                phases[phase_name] = []
            phases[phase_name].append(task)

        for phase_name, phase_tasks in phases.items():
            phase_input = 0
            phase_output = 0
            phase_min_time = 0
            phase_max_time = 0

            for _task in phase_tasks:
                task_tokens = self.TOKEN_ESTIMATES["task_execution"]
                phase_input += task_tokens["input"]
                phase_output += task_tokens["output"]

                exec_time = self.TIME_ESTIMATES["task_execution"]
                phase_min_time += exec_time[0]
                phase_max_time += exec_time[1]

                if verify:
                    verify_time = self.TIME_ESTIMATES["verification"]
                    phase_min_time += verify_time[0]
                    phase_max_time += verify_time[1]

            phase_input_cost = (phase_input / 1_000_000) * self.cost_rates["input"]
            phase_output_cost = (phase_output / 1_000_000) * self.cost_rates["output"]
            phase_cost = phase_input_cost + phase_output_cost

            breakdown[phase_name] = {
                "tasks": len(phase_tasks),
                "input_tokens": phase_input,
                "output_tokens": phase_output,
                "cost": phase_cost,
                "time_min": phase_min_time // 60,
                "time_max": phase_max_time // 60,
            }

        return breakdown

    def estimate_task(self, task: Task, verify: bool = True) -> CostEstimate:
        return self.estimate_workflow([task], generate_plan=False, verify=verify)

    def get_model_comparison(self, tasks: list[Task]) -> dict[str, CostEstimate]:
        comparison = {}

        for model_name in self.MODEL_COSTS:
            estimator = CostEstimator(model=model_name)
            estimate = estimator.estimate_workflow(tasks, generate_plan=False, verify=True)
            comparison[model_name] = estimate

        return comparison

    def recommend_model(self, tasks: list[Task], budget_usd: float | None = None) -> str:
        comparisons = self.get_model_comparison(tasks)

        if budget_usd:
            affordable = {
                model: est
                for model, est in comparisons.items()
                if est.estimated_cost_usd <= budget_usd
            }
            if not affordable:
                self.logger.warning(
                    f"No models fit budget of ${budget_usd:.2f}, "
                    f"cheapest is "
                    f"${min(e.estimated_cost_usd for e in comparisons.values()):.2f}"
                )
                return min(comparisons.items(), key=lambda x: x[1].estimated_cost_usd)[0]
            comparisons = affordable

        avg_files_per_task = sum(len(t.files) for t in tasks) / len(tasks)

        if avg_files_per_task < 2:
            if "gpt-4o-mini" in comparisons:
                return "gpt-4o-mini"
            if "claude-haiku-4-20250414" in comparisons:
                return "claude-haiku-4-20250414"

        if "claude-sonnet-4-20250514" in comparisons:
            return "claude-sonnet-4-20250514"

        return "gpt-4o"
