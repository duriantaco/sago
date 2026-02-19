"""Tests for GitIntegration with mocked subprocess calls."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sago.utils.git_integration import _GIT_TIMEOUT, GitIntegration


@pytest.fixture
def git(tmp_path: Path) -> GitIntegration:
    (tmp_path / ".git").mkdir()
    return GitIntegration(tmp_path)


@pytest.fixture
def git_no_repo(tmp_path: Path) -> GitIntegration:
    return GitIntegration(tmp_path)


class TestIsGitRepo:
    def test_true_when_git_dir_exists(self, git: GitIntegration) -> None:
        assert git.is_git_repo() is True

    def test_false_when_no_git_dir(self, git_no_repo: GitIntegration) -> None:
        assert git_no_repo.is_git_repo() is False


class TestInitRepo:
    def test_already_exists(self, git: GitIntegration) -> None:
        assert git.init_repo() is True

    @patch("sago.utils.git_integration.subprocess.run")
    def test_success(self, mock_run: MagicMock, git_no_repo: GitIntegration) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        assert git_no_repo.init_repo() is True
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["timeout"] == _GIT_TIMEOUT

    @patch("sago.utils.git_integration.subprocess.run")
    def test_failure(self, mock_run: MagicMock, git_no_repo: GitIntegration) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="error")
        assert git_no_repo.init_repo() is False

    @patch("sago.utils.git_integration.subprocess.run")
    def test_timeout(self, mock_run: MagicMock, git_no_repo: GitIntegration) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired("git", _GIT_TIMEOUT)
        assert git_no_repo.init_repo() is False


class TestCreateCommit:
    def test_not_a_repo(self, git_no_repo: GitIntegration) -> None:
        assert git_no_repo.create_commit("1.1", "test", ["f.py"]) is False

    @patch("sago.utils.git_integration.subprocess.run")
    def test_success(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.return_value = MagicMock(stdout="M f.py", returncode=0)
        assert git.create_commit("1.1", "test task", ["f.py"]) is True

    @patch("sago.utils.git_integration.subprocess.run")
    def test_no_changes(self, mock_run: MagicMock, git: GitIntegration) -> None:
        # git add succeeds, git status returns empty (no changes)
        def side_effect(*args: object, **kwargs: object) -> MagicMock:
            cmd = args[0]
            if cmd[1] == "status":
                return MagicMock(stdout="", returncode=0)
            return MagicMock(returncode=0)

        mock_run.side_effect = side_effect
        assert git.create_commit("1.1", "test", ["f.py"]) is True

    @patch("sago.utils.git_integration.subprocess.run")
    def test_failure(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="fail")
        assert git.create_commit("1.1", "test", ["f.py"]) is False

    @patch("sago.utils.git_integration.subprocess.run")
    def test_timeout(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired("git", _GIT_TIMEOUT)
        assert git.create_commit("1.1", "test", ["f.py"]) is False


class TestCreateBranch:
    def test_not_a_repo(self, git_no_repo: GitIntegration) -> None:
        assert git_no_repo.create_branch("feature") is False

    @patch("sago.utils.git_integration.subprocess.run")
    def test_success(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        assert git.create_branch("feature-x") is True

    @patch("sago.utils.git_integration.subprocess.run")
    def test_failure(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="exists")
        assert git.create_branch("main") is False


class TestGetCurrentBranch:
    @patch("sago.utils.git_integration.subprocess.run")
    def test_success(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.return_value = MagicMock(stdout="main\n", returncode=0)
        assert git.get_current_branch() == "main"

    @patch("sago.utils.git_integration.subprocess.run")
    def test_failure(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert git.get_current_branch() is None


class TestPushBranch:
    @patch("sago.utils.git_integration.subprocess.run")
    def test_success(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
        assert git.push_branch("main") is True

    @patch("sago.utils.git_integration.subprocess.run")
    def test_failure(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="denied")
        assert git.push_branch("main") is False

    @patch("sago.utils.git_integration.subprocess.run")
    def test_no_branch_name(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert git.push_branch() is False


class TestCheckpoint:
    @patch("sago.utils.git_integration.subprocess.run")
    def test_create_checkpoint(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        result = git.create_checkpoint("v1")
        assert result == "sago-checkpoint-v1"

    @patch("sago.utils.git_integration.subprocess.run")
    def test_create_checkpoint_failure(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="fail")
        assert git.create_checkpoint("v1") is None

    @patch("sago.utils.git_integration.subprocess.run")
    def test_rollback(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        assert git.rollback_to_checkpoint("sago-checkpoint-v1") is True

    @patch("sago.utils.git_integration.subprocess.run")
    def test_rollback_failure(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="fail")
        assert git.rollback_to_checkpoint("bad") is False


class TestFileDiff:
    @patch("sago.utils.git_integration.subprocess.run")
    def test_success(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.return_value = MagicMock(stdout="--- a/f.py\n+++ b/f.py", returncode=0)
        assert git.get_file_diff("f.py") is not None

    @patch("sago.utils.git_integration.subprocess.run")
    def test_failure(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert git.get_file_diff("f.py") is None


class TestUndoLastCommit:
    @patch("sago.utils.git_integration.subprocess.run")
    def test_soft(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        assert git.undo_last_commit(keep_changes=True) is True
        assert "--soft" in mock_run.call_args[0][0]

    @patch("sago.utils.git_integration.subprocess.run")
    def test_hard(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        assert git.undo_last_commit(keep_changes=False) is True
        assert "--hard" in mock_run.call_args[0][0]

    @patch("sago.utils.git_integration.subprocess.run")
    def test_failure(self, mock_run: MagicMock, git: GitIntegration) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="fail")
        assert git.undo_last_commit() is False
