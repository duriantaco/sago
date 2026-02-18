import pytest

from sago.core.parser import Task
from sago.utils.cost_estimator import CostEstimator


@pytest.fixture
def estimator() -> CostEstimator:
    return CostEstimator(model="gpt-4o")


@pytest.fixture
def sample_tasks() -> list[Task]:
    return [
        Task(
            id="1.1", name="Task A", files=["a.py"],
            action="Do A", verify="pytest", done="Done A", phase_name="Phase 1",
        ),
        Task(
            id="1.2", name="Task B", files=["b.py"],
            action="Do B", verify="pytest", done="Done B", phase_name="Phase 1",
        ),
        Task(
            id="2.1", name="Task C", files=["c.py"],
            action="Do C", verify="pytest", done="Done C", phase_name="Phase 2",
        ),
    ]


def test_known_model_uses_correct_pricing(estimator: CostEstimator) -> None:
    assert estimator.cost_rates == {"input": 2.50, "output": 10.00}


def test_unknown_model_falls_back_to_gpt4o() -> None:
    est = CostEstimator(model="unknown-model-xyz")
    assert est.cost_rates == CostEstimator.MODEL_COSTS["gpt-4o"]



def test_estimate_returns_correct_task_count(
    estimator: CostEstimator, sample_tasks: list[Task]
) -> None:
    estimate = estimator.estimate_workflow(sample_tasks)
    assert estimate.total_tasks == 3


def test_estimate_tokens_positive(
    estimator: CostEstimator, sample_tasks: list[Task]
) -> None:
    estimate = estimator.estimate_workflow(sample_tasks)
    assert estimate.estimated_input_tokens > 0
    assert estimate.estimated_output_tokens > 0
    assert estimate.estimated_total_tokens == (
        estimate.estimated_input_tokens + estimate.estimated_output_tokens
    )


def test_estimate_cost_positive(
    estimator: CostEstimator, sample_tasks: list[Task]
) -> None:
    estimate = estimator.estimate_workflow(sample_tasks)
    assert estimate.estimated_cost_usd > 0


def test_estimate_duration_is_range(
    estimator: CostEstimator, sample_tasks: list[Task]
) -> None:
    estimate = estimator.estimate_workflow(sample_tasks)
    min_time, max_time = estimate.estimated_duration_seconds
    assert min_time > 0
    assert max_time >= min_time


def test_plan_generation_adds_cost(
    estimator: CostEstimator, sample_tasks: list[Task]
) -> None:
    without_plan = estimator.estimate_workflow(sample_tasks, generate_plan=False)
    with_plan = estimator.estimate_workflow(sample_tasks, generate_plan=True)
    assert with_plan.estimated_cost_usd > without_plan.estimated_cost_usd
    assert with_plan.estimated_total_tokens > without_plan.estimated_total_tokens


def test_verification_adds_time(
    estimator: CostEstimator, sample_tasks: list[Task]
) -> None:
    without_verify = estimator.estimate_workflow(sample_tasks, verify=False)
    with_verify = estimator.estimate_workflow(sample_tasks, verify=True)
    _, max_no_verify = without_verify.estimated_duration_seconds
    _, max_verify = with_verify.estimated_duration_seconds
    assert max_verify > max_no_verify


def test_breakdown_by_phase(
    estimator: CostEstimator, sample_tasks: list[Task]
) -> None:
    estimate = estimator.estimate_workflow(sample_tasks)
    assert "Phase 1" in estimate.breakdown_by_phase
    assert "Phase 2" in estimate.breakdown_by_phase
    assert estimate.breakdown_by_phase["Phase 1"]["tasks"] == 2
    assert estimate.breakdown_by_phase["Phase 2"]["tasks"] == 1


def test_phase_costs_sum_to_total(
    estimator: CostEstimator, sample_tasks: list[Task]
) -> None:
    """Phase costs should approximately sum to total (minus plan generation)."""
    estimate = estimator.estimate_workflow(sample_tasks, generate_plan=False)
    phase_cost_sum = sum(p["cost"] for p in estimate.breakdown_by_phase.values())
    assert abs(phase_cost_sum - estimate.estimated_cost_usd) < 0.001



def test_estimate_single_task(estimator: CostEstimator, sample_tasks: list[Task]) -> None:
    estimate = estimator.estimate_task(sample_tasks[0])
    assert estimate.total_tasks == 1
    assert estimate.estimated_cost_usd > 0



def test_model_comparison_covers_all_models(
    estimator: CostEstimator, sample_tasks: list[Task]
) -> None:
    comparison = estimator.get_model_comparison(sample_tasks)
    for model in CostEstimator.MODEL_COSTS:
        assert model in comparison
        assert comparison[model].estimated_cost_usd > 0


def test_cheaper_model_costs_less(sample_tasks: list[Task]) -> None:
    est = CostEstimator(model="gpt-4o")
    comparison = est.get_model_comparison(sample_tasks)
    assert comparison["gpt-4o-mini"].estimated_cost_usd < comparison["gpt-4o"].estimated_cost_usd


def test_cost_estimate_str(
    estimator: CostEstimator, sample_tasks: list[Task]
) -> None:
    estimate = estimator.estimate_workflow(sample_tasks)
    s = str(estimate)
    assert "Cost Estimate:" in s
    assert "Total Tasks: 3" in s
    assert "$" in s
    assert "gpt-4o" in s
