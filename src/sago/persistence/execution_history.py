"""Execution-history and receipt persistence."""

from __future__ import annotations

from pathlib import Path

from sago.models.execution import CheckpointReceipt, ExecutionHistory


class ExecutionHistoryStore:
    """Persist raw receipts and derived execution history under .planning/runtime."""

    def __init__(self, project_path: Path) -> None:
        self.project_path = project_path
        self.runtime_dir = project_path / ".planning" / "runtime"
        self.receipts_dir = self.runtime_dir / "receipts"
        self.history_path = self.runtime_dir / "execution_history.json"

    def load(self) -> ExecutionHistory:
        if not self.history_path.exists():
            return ExecutionHistory()
        return ExecutionHistory.from_json(self.history_path.read_text(encoding="utf-8"))

    def save(self, history: ExecutionHistory) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.history_path.write_text(history.to_json(), encoding="utf-8")

    def append_receipt(self, receipt: CheckpointReceipt) -> CheckpointReceipt:
        """Persist a receipt and append its derived execution record."""
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.receipts_dir.mkdir(parents=True, exist_ok=True)

        receipt_path = self.receipts_dir / f"{receipt.receipt_id}.json"
        receipt_path.write_text(receipt.model_dump_json(indent=2), encoding="utf-8")

        history = self.load()
        task_id = receipt.task_id or ""
        attempt = history.attempts_for_task(task_id) + 1
        history.records.append(receipt.to_execution_record(attempt))
        self.save(history)
        return receipt
