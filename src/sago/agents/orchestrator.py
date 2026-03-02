import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sago.agents.base import AgentResult
from sago.agents.planner import PlannerAgent
from sago.agents.replanner import ReplannerAgent
from sago.agents.reviewer import ReviewerAgent
from sago.core.config import Config
from sago.core.parser import MarkdownParser, Phase
from sago.core.project import ProjectManager
from sago.utils.tracer import tracer

logger = logging.getLogger(__name__)


@dataclass
class WorkflowResult:
    success: bool
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    skipped_tasks: int
    total_duration: float
    task_executions: list[Any] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "skipped_tasks": self.skipped_tasks,
            "total_duration": self.total_duration,
            "error": self.error,
        }


def _failed_workflow(duration: float, error: str, total_tasks: int = 0) -> WorkflowResult:
    return WorkflowResult(
        success=False,
        total_tasks=total_tasks,
        completed_tasks=0,
        failed_tasks=0,
        skipped_tasks=total_tasks,
        total_duration=duration,
        error=error,
    )


class Orchestrator:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self.logger = logging.getLogger(self.__class__.__name__)

        from sago.utils.llm import LLMClient

        planner_llm = LLMClient(
            model=self.config.effective_planner_model,
            api_key=self.config.llm_api_key,
            temperature=self.config.llm_temperature,
            max_tokens=self.config.llm_max_tokens,
        )

        self.planner = PlannerAgent(config=self.config, llm_client=planner_llm)
        self.replanner = ReplannerAgent(config=self.config, llm_client=planner_llm)

        judge_llm = LLMClient(
            model=self.config.effective_judge_model,
            api_key=self.config.get_judge_api_key(),
            temperature=self.config.llm_temperature,
            max_tokens=self.config.llm_max_tokens,
        )
        self.reviewer = ReviewerAgent(config=self.config, llm_client=judge_llm)

        self.parser = MarkdownParser()
        self.project_manager = ProjectManager(self.config)

    async def run_workflow(
        self,
        project_path: Path,
        plan: bool = True,
        **kwargs: Any,
    ) -> WorkflowResult:
        """Run the planning workflow.

        Args:
            project_path: Path to the project directory.
            plan: Whether to generate PLAN.md.
            **kwargs: Accepted for backwards compatibility but ignored.
        """
        if self.config.enable_tracing:
            trace_path = self.config.trace_file or (project_path / ".planning" / "trace.jsonl")
            tracer.configure(trace_path, model=self.config.llm_model)
            self.logger.info(f"Tracing enabled: {trace_path}")

        start_time = datetime.now()
        self.logger.info(f"Starting workflow for project: {project_path}")

        tracer.emit(
            "workflow_start",
            "Orchestrator",
            {"project_path": str(project_path), "flags": {"plan": plan}},
        )

        def _elapsed() -> float:
            return (datetime.now() - start_time).total_seconds()

        try:
            phases = await self._load_plan(project_path, generate=plan)
            all_tasks = [task for phase in phases for task in phase.tasks]

            return WorkflowResult(
                success=True,
                total_tasks=len(all_tasks),
                completed_tasks=0,
                failed_tasks=0,
                skipped_tasks=len(all_tasks),
                total_duration=_elapsed(),
            )

        except ValueError as e:
            tracer.emit("error", "Orchestrator", {"error_type": "workflow", "message": str(e)})
            return _failed_workflow(_elapsed(), str(e))
        except Exception as e:
            self.logger.error(f"Workflow failed: {e}", exc_info=True)
            tracer.emit("error", "Orchestrator", {"error_type": "workflow", "message": str(e)})
            return _failed_workflow(_elapsed(), str(e))
        finally:
            tracer.close()

    async def run_review(self, project_path: Path, phase: Phase, review_prompt: str) -> AgentResult:
        """Run the reviewer agent on a completed phase.

        Args:
            project_path: Path to the project directory.
            phase: The completed Phase to review.
            review_prompt: Instructions for the review.

        Returns:
            AgentResult with review output.
        """
        return await self.reviewer.execute(
            {
                "project_path": project_path,
                "phase": phase,
                "review_prompt": review_prompt,
            }
        )

    async def run_replan_workflow(
        self,
        project_path: Path,
        feedback: str,
        review_context: str = "",
        repo_map: str = "",
    ) -> WorkflowResult:
        """Run the replan workflow — update PLAN.md based on user feedback.

        Args:
            project_path: Path to the project directory.
            feedback: Natural language change request from the user.
            review_context: Optional review output from ReviewerAgent.
            repo_map: Optional repo map string for code-aware replanning.
        """
        if self.config.enable_tracing:
            trace_path = self.config.trace_file or (project_path / ".planning" / "trace.jsonl")
            tracer.configure(trace_path, model=self.config.llm_model)

        start_time = datetime.now()
        self.logger.info(f"Starting replan workflow for project: {project_path}")

        tracer.emit(
            "workflow_start",
            "Orchestrator",
            {"project_path": str(project_path), "flags": {"replan": True}},
        )

        def _elapsed() -> float:
            return (datetime.now() - start_time).total_seconds()

        try:
            result = await self.replanner.execute(
                {
                    "project_path": project_path,
                    "feedback": feedback,
                    "review_context": review_context,
                    "repo_map": repo_map,
                }
            )

            if not result.success:
                raise ValueError(f"Replan failed: {result.error}")

            phases = self._load_plan_phases(project_path)
            all_tasks = [task for phase in phases for task in phase.tasks]

            return WorkflowResult(
                success=True,
                total_tasks=len(all_tasks),
                completed_tasks=0,
                failed_tasks=0,
                skipped_tasks=len(all_tasks),
                total_duration=_elapsed(),
            )

        except ValueError as e:
            tracer.emit("error", "Orchestrator", {"error_type": "replan", "message": str(e)})
            return _failed_workflow(_elapsed(), str(e))
        except Exception as e:
            self.logger.error(f"Replan workflow failed: {e}", exc_info=True)
            tracer.emit("error", "Orchestrator", {"error_type": "replan", "message": str(e)})
            return _failed_workflow(_elapsed(), str(e))
        finally:
            tracer.close()

    def _load_plan_phases(self, project_path: Path) -> list[Phase]:
        """Load phases from an existing PLAN.md (no generation)."""
        plan_path = project_path / "PLAN.md"
        if not plan_path.exists():
            raise ValueError("PLAN.md not found")
        plan_content = plan_path.read_text(encoding="utf-8")
        phases = self.parser.parse_xml_tasks(plan_content)
        if not phases:
            raise ValueError("No tasks found in PLAN.md")
        return phases

    async def _load_plan(self, project_path: Path, generate: bool) -> list[Phase]:
        """Load phases from PLAN.md, optionally generating it first."""
        plan_path = project_path / "PLAN.md"

        if generate:
            self.logger.info("Generating plan...")
            plan_result = await self.planner.execute({"project_path": project_path})
            if not plan_result.success:
                raise ValueError(f"Plan generation failed: {plan_result.error}")

        if not plan_path.exists():
            raise ValueError("PLAN.md not found")

        plan_content = plan_path.read_text(encoding="utf-8")

        if not generate and "Run `sago plan` to generate this file" in plan_content:
            raise ValueError(
                "PLAN.md is still the template — no real tasks to execute.\n"
                "  Run `sago plan` first to generate a plan from your "
                "PROJECT.md and REQUIREMENTS.md."
            )

        phases = self.parser.parse_xml_tasks(plan_content)
        if not phases:
            raise ValueError("No tasks found in PLAN.md")

        all_tasks = [task for phase in phases for task in phase.tasks]
        self.logger.info(f"Found {len(all_tasks)} tasks across {len(phases)} phases")
        return phases
