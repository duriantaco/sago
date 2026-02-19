import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sago.agents.base import AgentResult, AgentStatus
from sago.agents.dependencies import CircularDependencyError, DependencyResolver
from sago.agents.executor import ExecutorAgent
from sago.agents.planner import PlannerAgent
from sago.agents.self_healing import SelfHealingAgent
from sago.agents.verifier import VerifierAgent
from sago.core.config import Config
from sago.core.parser import MarkdownParser, Task
from sago.core.project import ProjectManager
from sago.utils.cache import SmartCache
from sago.utils.compression import ContextManager
from sago.utils.git_integration import GitIntegration
from sago.utils.paths import safe_resolve
from sago.utils.tracer import tracer

logger = logging.getLogger(__name__)


@dataclass
class TaskExecution:
    task: Task
    execution_result: AgentResult
    verification_result: AgentResult | None = None
    start_time: datetime = field(default_factory=datetime.now)
    end_time: datetime | None = None
    retry_count: int = 0

    @property
    def duration(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    @property
    def success(self) -> bool:
        return self.execution_result.success and (
            self.verification_result is None or self.verification_result.success
        )


@dataclass
class WorkflowResult:
    success: bool
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    skipped_tasks: int
    total_duration: float
    task_executions: list[TaskExecution] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "skipped_tasks": self.skipped_tasks,
            "total_duration": self.total_duration,
            "task_results": [
                {
                    "task_id": te.task.id,
                    "task_name": te.task.name,
                    "success": te.success,
                    "duration": te.duration,
                    "retry_count": te.retry_count,
                }
                for te in self.task_executions
            ],
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

        context_manager: ContextManager | None = None
        if self.config.enable_compression:
            context_manager = ContextManager(
                max_context_tokens=self.config.max_context_tokens,
                default_compressor="sliding_window",
            )

        from sago.utils.llm import LLMClient

        shared_llm = LLMClient(
            model=self.config.llm_model,
            api_key=self.config.llm_api_key,
            temperature=self.config.llm_temperature,
            max_tokens=self.config.llm_max_tokens,
        )

        self.planner = PlannerAgent(config=self.config, llm_client=shared_llm)
        self.executor = ExecutorAgent(
            config=self.config, llm_client=shared_llm, context_manager=context_manager
        )
        self.verifier = VerifierAgent(config=self.config, llm_client=shared_llm)
        self.self_healer = SelfHealingAgent(config=self.config, llm_client=shared_llm)
        self.dependency_resolver = DependencyResolver()

        self.parser = MarkdownParser()
        self.project_manager = ProjectManager(self.config)

        self.git: GitIntegration | None = None
        self.enable_self_healing: bool = False
        self.cache: SmartCache | None = None

    def _setup_workflow(
        self,
        project_path: Path,
        git_commit: bool,
        self_heal: bool,
        use_cache: bool,
    ) -> None:
        self.enable_self_healing = self_heal

        if self.config.enable_tracing:
            trace_path = self.config.trace_file or (project_path / ".planning" / "trace.jsonl")
            tracer.configure(trace_path, model=self.config.llm_model)
            self.logger.info(f"Tracing enabled: {trace_path}")

        if git_commit:
            self.git = GitIntegration(project_path)
            if not self.git.is_git_repo():
                self.logger.warning("Not a git repo, disabling git commits")
                self.git = None
        else:
            self.git = None

        if use_cache:
            self.cache = SmartCache()
            self.logger.info("Task caching enabled")
        else:
            self.cache = None

    async def _load_plan(self, project_path: Path, generate: bool) -> list[Task]:
        """Load tasks from PLAN.md, optionally generating it first.

        Returns list of tasks. Raises ValueError on failure.
        """
        if generate:
            plan_path = project_path / "PLAN.md"
            if not plan_path.exists():
                self.logger.info("Generating plan...")
                plan_result = await self.planner.execute({"project_path": project_path})
                if not plan_result.success:
                    raise ValueError(f"Plan generation failed: {plan_result.error}")

        plan_path = project_path / "PLAN.md"
        if not plan_path.exists():
            raise ValueError("PLAN.md not found")

        phases = self.parser.parse_xml_tasks(plan_path.read_text(encoding="utf-8"))
        if not phases:
            raise ValueError("No tasks found in PLAN.md")

        all_tasks = [task for phase in phases for task in phase.tasks]
        self.logger.info(f"Found {len(all_tasks)} tasks across {len(phases)} phases")
        return all_tasks

    async def run_workflow(
        self,
        project_path: Path,
        plan: bool = True,
        execute: bool = True,
        verify: bool = True,
        max_retries: int = 2,
        continue_on_failure: bool = False,
        git_commit: bool = False,
        self_heal: bool = False,
        use_cache: bool = False,
    ) -> WorkflowResult:
        self._setup_workflow(project_path, git_commit, self_heal, use_cache)

        start_time = datetime.now()
        self.logger.info(f"Starting workflow for project: {project_path}")

        tracer.emit(
            "workflow_start",
            "Orchestrator",
            {
                "project_path": str(project_path),
                "flags": {
                    "plan": plan,
                    "execute": execute,
                    "verify": verify,
                    "use_cache": use_cache,
                    "git_commit": git_commit,
                    "self_heal": self_heal,
                },
            },
        )

        def _elapsed() -> float:
            return (datetime.now() - start_time).total_seconds()

        try:
            all_tasks = await self._load_plan(project_path, generate=plan)

            if execute:
                result = await self._execute_tasks(
                    all_tasks,
                    project_path,
                    verify=verify,
                    max_retries=max_retries,
                    continue_on_failure=continue_on_failure,
                )
                tracer.emit(
                    "workflow_end",
                    "Orchestrator",
                    {
                        "success": result.success,
                        "total_tasks": result.total_tasks,
                        "completed": result.completed_tasks,
                        "failed": result.failed_tasks,
                        "duration_s": round(result.total_duration, 2),
                    },
                )
                return result

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

    async def _record_task_result(self, task_exec: TaskExecution, project_path: Path) -> None:
        if task_exec.success:
            self.logger.info(f"Task {task_exec.task.id} completed in {task_exec.duration:.1f}s")
            await self._update_state(project_path, task_exec.task, success=True)
        else:
            self.logger.error(
                f"Task {task_exec.task.id} failed: {task_exec.execution_result.error}"
            )
            await self._update_state(
                project_path,
                task_exec.task,
                success=False,
                error=task_exec.execution_result.error,
            )

    async def _execute_tasks(
        self,
        tasks: list[Task],
        project_path: Path,
        verify: bool = True,
        max_retries: int = 2,
        continue_on_failure: bool = False,
    ) -> WorkflowResult:
        waves = self._resolve_waves(tasks)
        if isinstance(waves, WorkflowResult):
            return waves

        start_time = datetime.now()
        task_executions: list[TaskExecution] = []
        completed = 0
        failed = 0

        try:
            completed, failed = await self._run_waves(
                waves,
                project_path,
                task_executions,
                verify=verify,
                max_retries=max_retries,
                continue_on_failure=continue_on_failure,
            )
            return self._build_workflow_result(
                tasks,
                task_executions,
                completed,
                failed,
                start_time,
            )
        except Exception as e:
            self.logger.error(f"Task execution failed: {e}", exc_info=True)
            return WorkflowResult(
                success=False,
                total_tasks=len(tasks),
                completed_tasks=completed,
                failed_tasks=failed,
                skipped_tasks=len(tasks) - completed - failed,
                total_duration=(datetime.now() - start_time).total_seconds(),
                task_executions=task_executions,
                error=str(e),
            )

    def _resolve_waves(self, tasks: list[Task]) -> list[list[Task]] | WorkflowResult:
        try:
            waves = self.dependency_resolver.resolve(tasks)
            self.logger.info(f"Resolved {len(tasks)} tasks into {len(waves)} waves")
            return waves
        except CircularDependencyError as e:
            self.logger.error(f"Circular dependency detected: {e}")
            return _failed_workflow(0.0, str(e), total_tasks=len(tasks))

    async def _run_waves(
        self,
        waves: list[list[Task]],
        project_path: Path,
        task_executions: list[TaskExecution],
        verify: bool,
        max_retries: int,
        continue_on_failure: bool,
    ) -> tuple[int, int]:
        completed = 0
        failed = 0
        for wave_num, wave in enumerate(waves, 1):
            self.logger.info(f"Executing wave {wave_num}/{len(waves)} ({len(wave)} tasks)")
            wave_results = await self._execute_wave(
                wave, project_path, verify=verify, max_retries=max_retries
            )
            for task_exec in wave_results:
                task_executions.append(task_exec)
                await self._record_task_result(task_exec, project_path)
                if task_exec.success:
                    completed += 1
                else:
                    failed += 1
                    if not continue_on_failure:
                        break
            if failed > 0 and not continue_on_failure:
                break
        return completed, failed

    def _build_workflow_result(
        self,
        tasks: list[Task],
        task_executions: list[TaskExecution],
        completed: int,
        failed: int,
        start_time: datetime,
    ) -> WorkflowResult:
        skipped = len(tasks) - completed - failed
        total_duration = (datetime.now() - start_time).total_seconds()
        self.logger.info(
            f"Workflow completed: {completed}/{len(tasks)} tasks successful "
            f"({failed} failed, {skipped} skipped) in {total_duration:.1f}s"
        )
        return WorkflowResult(
            success=failed == 0,
            total_tasks=len(tasks),
            completed_tasks=completed,
            failed_tasks=failed,
            skipped_tasks=skipped,
            total_duration=total_duration,
            task_executions=task_executions,
        )

    async def _execute_wave(
        self,
        wave: list[Task],
        project_path: Path,
        verify: bool = True,
        max_retries: int = 2,
    ) -> list[TaskExecution]:
        if self.config.enable_parallel_execution:
            self.logger.info(f"Executing {len(wave)} tasks in parallel")
            return await self._execute_wave_parallel(wave, project_path, verify, max_retries)

        results: list[TaskExecution] = []
        for task in wave:
            try:
                result = await self._execute_single_task(task, project_path, verify, max_retries)
                results.append(result)
            except Exception as e:
                results.append(self._failed_task_execution(task, e))
        return results

    async def _execute_wave_parallel(
        self,
        wave: list[Task],
        project_path: Path,
        verify: bool,
        max_retries: int,
    ) -> list[TaskExecution]:
        semaphore = asyncio.Semaphore(self.config.max_concurrent_tasks)
        results: dict[str, TaskExecution] = {}

        async def _run(task: Task) -> None:
            async with semaphore:
                try:
                    results[task.id] = await self._execute_single_task(
                        task, project_path, verify, max_retries
                    )
                except Exception as e:
                    results[task.id] = self._failed_task_execution(task, e)

        try:
            async with asyncio.TaskGroup() as tg:
                for task in wave:
                    tg.create_task(_run(task))
        except ExceptionGroup as eg:
            for exc in eg.exceptions:
                self.logger.error(f"Parallel task error: {exc}")

        return [
            results.get(t.id, self._failed_task_execution(t, RuntimeError("not started")))
            for t in wave
        ]

    def _failed_task_execution(self, task: Task, error: Exception) -> TaskExecution:
        self.logger.error(f"Task {task.id} raised exception: {error}")
        return TaskExecution(
            task=task,
            execution_result=AgentResult(
                status=AgentStatus.FAILURE,
                output="",
                error=str(error),
                metadata={},
            ),
            start_time=datetime.now(),
            end_time=datetime.now(),
        )

    def _check_cache(
        self, task: Task, project_path: Path
    ) -> tuple[str | None, dict[str, str], TaskExecution | None]:
        if self.cache is None:
            return None, {}, None

        task_data: dict[str, Any] = {
            "id": task.id,
            "name": task.name,
            "action": task.action,
            "files": task.files,
            "verify": task.verify,
            "done": task.done,
        }
        pre_exec_file_contents: dict[str, str] = {}

        for file_path_str in task.files:
            file_path = safe_resolve(project_path, file_path_str)
            if file_path.exists():
                try:
                    content = file_path.read_text(encoding="utf-8")
                    task_data.setdefault("file_contents", {})[file_path_str] = content
                    pre_exec_file_contents[file_path_str] = content
                except (OSError, UnicodeDecodeError):
                    pass

        task_hash = self.cache.get_task_hash(task_data)
        cached = self.cache.get_cached_result(task_hash)

        if cached is None:
            return task_hash, pre_exec_file_contents, None

        self.logger.info(f"Cache hit for task {task.id}, skipping execution")
        for file_path_str, content in cached.get("files", {}).items():
            file_path = safe_resolve(project_path, file_path_str)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")

        return (
            task_hash,
            pre_exec_file_contents,
            TaskExecution(
                task=task,
                execution_result=AgentResult(
                    status=AgentStatus.SUCCESS,
                    output="Restored from cache",
                    metadata=cached.get("metadata", {}),
                ),
                start_time=datetime.now(),
                end_time=datetime.now(),
            ),
        )

    def _save_cache(
        self,
        task: Task,
        task_hash: str,
        pre_exec_file_contents: dict[str, str],
        metadata: dict[str, Any],
        project_path: Path,
    ) -> None:
        cached_files = {}
        for file_path_str in task.files:
            file_path = safe_resolve(project_path, file_path_str)
            if file_path.exists():
                try:
                    current_content = file_path.read_text(encoding="utf-8")
                    pre_exec = pre_exec_file_contents.get(file_path_str)
                    if pre_exec is None or current_content != pre_exec:
                        cached_files[file_path_str] = current_content
                except (OSError, UnicodeDecodeError):
                    pass

        if self.cache is not None:
            self.cache.set_cached_result(
                task_hash,
                {
                    "success": True,
                    "files": cached_files,
                    "metadata": metadata,
                },
            )
            self.logger.info(f"Cached result for task {task.id}")

    async def _execute_single_task(
        self, task: Task, project_path: Path, verify: bool = True, max_retries: int = 2
    ) -> TaskExecution:
        task_hash, pre_exec_contents, cached_exec = self._check_cache(task, project_path)
        if cached_exec is not None:
            tracer.emit("cache_hit", "Orchestrator", {"task_id": task.id})
            return cached_exec

        if self.cache is not None:
            tracer.emit("cache_miss", "Orchestrator", {"task_id": task.id})

        tracer.emit(
            "task_start",
            "Orchestrator",
            {"task_id": task.id, "task_name": task.name, "files": task.files},
        )

        task_exec = TaskExecution(
            task=task,
            execution_result=AgentResult(
                status=AgentStatus.PENDING, output="", error=None, metadata={}
            ),
            start_time=datetime.now(),
        )

        await self._retry_task(task, task_exec, project_path, verify, max_retries)
        self._finalize_task(task, task_exec, task_hash, pre_exec_contents, project_path)
        task_exec.end_time = datetime.now()

        tracer.emit(
            "task_end",
            "Orchestrator",
            {
                "task_id": task.id,
                "task_name": task.name,
                "success": task_exec.success,
                "duration_s": round(task_exec.duration, 2),
                "retry_count": task_exec.retry_count,
            },
        )

        return task_exec

    async def _retry_task(
        self,
        task: Task,
        task_exec: TaskExecution,
        project_path: Path,
        verify: bool,
        max_retries: int,
    ) -> None:
        context = {"task": task, "project_path": project_path}
        previous_attempts: list[str] = []
        for attempt in range(max_retries + 1):
            if attempt > 0:
                self.logger.info(f"Retrying task {task.id} (attempt {attempt + 1})")
                task_exec.retry_count = attempt

            task_exec.execution_result = await self.executor.execute(context)

            if not task_exec.execution_result.success:
                self.logger.warning(
                    f"Task {task.id} execution failed: {task_exec.execution_result.error}"
                )
                previous_attempts.append(f"Execution error: {task_exec.execution_result.error}")
                if self.enable_self_healing and attempt < max_retries:
                    await self._attempt_self_heal(task, task_exec, project_path, previous_attempts)
                continue

            if not verify:
                break

            task_exec.verification_result = await self.verifier.execute(context)
            if task_exec.verification_result.success:
                break

            self.logger.warning(
                f"Task {task.id} verification failed: {task_exec.verification_result.error}"
            )
            previous_attempts.append(f"Verification error: {task_exec.verification_result.error}")
            if self.enable_self_healing and attempt < max_retries:
                await self._attempt_self_heal(task, task_exec, project_path, previous_attempts)

    def _finalize_task(
        self,
        task: Task,
        task_exec: TaskExecution,
        task_hash: str | None,
        pre_exec_contents: dict[str, str],
        project_path: Path,
    ) -> None:
        if task_exec.success and self.cache is not None and task_hash is not None:
            self._save_cache(
                task,
                task_hash,
                pre_exec_contents,
                task_exec.execution_result.metadata,
                project_path,
            )
        if task_exec.success and self.git:
            files = task_exec.execution_result.metadata.get("files_modified", task.files)
            committed = self.git.create_commit(task_id=task.id, task_name=task.name, files=files)
            if committed:
                self.logger.info(f"Git commit created for task {task.id}")
            else:
                self.logger.warning(f"Git commit failed for task {task.id}")

    async def _attempt_self_heal(
        self,
        task: Task,
        task_exec: TaskExecution,
        project_path: Path,
        previous_attempts: list[str] | None = None,
    ) -> None:
        error = (
            task_exec.execution_result.error
            or (task_exec.verification_result.error if task_exec.verification_result else None)
            or "Unknown error"
        )

        if not self.self_healer.should_attempt_fix(error, task):
            self.logger.info(f"Self-healer skipping unfixable error for task {task.id}")
            return

        self.logger.info(f"Self-healer attempting fix for task {task.id}")

        original_code_parts = []
        for file_path_str in task.files:
            file_path = safe_resolve(project_path, file_path_str)
            if file_path.exists():
                try:
                    original_code_parts.append(
                        f"=== {file_path_str} ===\n{file_path.read_text(encoding='utf-8')}"
                    )
                except (OSError, UnicodeDecodeError):
                    pass

        verify_stdout = ""
        verify_stderr = ""
        if task_exec.verification_result and task_exec.verification_result.metadata:
            verify_stdout = task_exec.verification_result.metadata.get("stdout", "")
            verify_stderr = task_exec.verification_result.metadata.get("stderr", "")

        heal_context: dict[str, Any] = {
            "task": task,
            "error": error,
            "original_code": "\n\n".join(original_code_parts),
            "project_path": project_path,
            "verify_stdout": verify_stdout,
            "verify_stderr": verify_stderr,
            "previous_attempts": previous_attempts or [],
        }

        heal_result = await self.self_healer.execute(heal_context)
        if heal_result.success:
            self.logger.info(f"Self-healer generated fix for task {task.id}")
            fix_code = heal_result.metadata.get("fix_applied", {})
            for file_path_str, content in fix_code.items():
                file_path = safe_resolve(project_path, file_path_str)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding="utf-8")
                self.logger.info(f"Self-healer wrote fix to {file_path_str}")
        else:
            self.logger.warning(f"Self-healer could not fix task {task.id}: {heal_result.error}")

    async def _update_state(
        self,
        project_path: Path,
        task: Task,
        success: bool,
        error: str | None = None,
    ) -> None:
        try:
            self._write_state_entry(project_path, task, success, error)
        except Exception as e:
            self.logger.warning(f"Failed to update STATE.md: {e}")

    def _write_state_entry(
        self, project_path: Path, task: Task, success: bool, error: str | None
    ) -> None:
        state_path = project_path / "STATE.md"

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_mark = "✓" if success else "✗"
        entry = f"\n- [{status_mark}] {task.id}: {task.name} ({timestamp})"
        if error:
            entry += f"\n  - Error: {error}"

        mode = "a+" if state_path.exists() else "w+"
        with open(state_path, mode, encoding="utf-8") as f:
            if sys.platform != "win32":
                import fcntl

                fcntl.flock(f, fcntl.LOCK_EX)

            try:
                f.seek(0)
                content = f.read()

                if not content:
                    content = "# Project State\n\n## Completed Tasks\n\n"

                if "## Completed Tasks" in content:
                    parts = content.split("## Completed Tasks")
                    content = parts[0] + "## Completed Tasks\n" + parts[1] + entry
                else:
                    content += "\n## Completed Tasks\n" + entry

                f.seek(0)
                f.truncate()
                f.write(content)
            finally:
                if sys.platform != "win32":
                    import fcntl

                    fcntl.flock(f, fcntl.LOCK_UN)
