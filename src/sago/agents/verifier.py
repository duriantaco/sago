import asyncio
import logging
import shlex
import time
from pathlib import Path
from typing import Any

from sago.agents.base import AgentResult, AgentStatus, BaseAgent
from sago.core.parser import Task
from sago.utils.tracer import tracer

logger = logging.getLogger(__name__)


class VerifierAgent(BaseAgent):
    async def execute(self, context: dict[str, Any]) -> AgentResult:
        try:
            return await self._do_execute(context)
        except Exception as e:
            self.logger.error(f"Verification error: {e}")
            return self._create_result(
                status=AgentStatus.FAILURE,
                output="",
                error=str(e),
                metadata={"task_id": context.get("task", {}).get("id", "unknown")},
            )

    async def _do_execute(self, context: dict[str, Any]) -> AgentResult:
        task: Task = context["task"]
        project_path = Path(context.get("project_path", "."))

        self.logger.info(f"Verifying task {task.id}: {task.name}")
        verify_result = await self._run_verification(task, project_path)

        if verify_result["success"]:
            return self._create_result(
                status=AgentStatus.SUCCESS,
                output=f"Task {task.id} verified successfully",
                metadata={
                    "task_id": task.id,
                    "verify_command": task.verify,
                    "exit_code": verify_result["exit_code"],
                    "stdout": verify_result["stdout"][:500],
                },
            )
        return self._create_result(
            status=AgentStatus.FAILURE,
            output=f"Task {task.id} verification failed",
            error=verify_result["stderr"],
            metadata={
                "task_id": task.id,
                "verify_command": task.verify,
                "exit_code": verify_result["exit_code"],
                "stdout": verify_result["stdout"],
                "stderr": verify_result["stderr"],
            },
        )

    async def _run_verification(self, task: Task, project_path: Path) -> dict[str, Any]:
        if not task.verify or not task.verify.strip():
            self.logger.warning(f"Task {task.id} has no verification command")
            return {
                "success": True,
                "exit_code": 0,
                "stdout": "No verification command specified",
                "stderr": "",
            }

        self.logger.info(f"Running: {task.verify}")

        cmd = self._parse_command(task.verify)
        if cmd is None:
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Invalid command syntax: {task.verify}",
            }

        return await self._run_subprocess(cmd, project_path)

    def _parse_command(self, verify_str: str) -> list[str] | None:
        try:
            return shlex.split(verify_str)
        except ValueError as e:
            self.logger.error(f"Invalid verify command syntax: {e}")
            return None

    async def _run_subprocess(self, cmd: list[str], project_path: Path) -> dict[str, Any]:
        start = time.monotonic()
        command_str = " ".join(cmd)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self.config.verify_timeout
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            duration_s = time.monotonic() - start
            self.logger.error(f"Verification timed out after {self.config.verify_timeout}s")
            tracer.emit(
                "verify_run",
                "VerifierAgent",
                {
                    "command": command_str,
                    "exit_code": -1,
                    "success": False,
                    "duration_s": round(duration_s, 3),
                },
            )
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Command timed out after {self.config.verify_timeout} seconds",
            }
        except Exception as e:
            duration_s = time.monotonic() - start
            self.logger.error(f"Verification command failed: {e}")
            tracer.emit(
                "verify_run",
                "VerifierAgent",
                {
                    "command": command_str,
                    "exit_code": -1,
                    "success": False,
                    "duration_s": round(duration_s, 3),
                },
            )
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
            }

        duration_s = time.monotonic() - start
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        returncode = proc.returncode or 0
        success = returncode == 0

        self.logger.info(
            f"Verification {'passed' if success else 'failed'} (exit code: {returncode})"
        )
        tracer.emit(
            "verify_run",
            "VerifierAgent",
            {
                "command": command_str,
                "exit_code": returncode,
                "success": success,
                "duration_s": round(duration_s, 3),
                "stdout": stdout[:2000],
                "stderr": stderr[:2000],
            },
        )
        return {
            "success": success,
            "exit_code": returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
