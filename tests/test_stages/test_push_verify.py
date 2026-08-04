"""Tests for push/verify.py — commit and push branch."""

from pathlib import Path
from unittest.mock import patch

import pytest

import forger.stages.push.verify as push_verify
from forger.state import load_change, save_change
from tests import make_state


@pytest.fixture
def run_dir(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    return d


def _write_commit_file(run_dir: Path):
    (run_dir / "commit.txt").write_text("fix: resolve bug")


class TestPushVerifyGuards:
    def test_terminal_stage_returns_false(self, run_dir, config):
        state = make_state(stage="pr-open")
        save_change(run_dir / "change.md", state, "body")
        assert push_verify.verify(run_dir, config) is False

    def test_parked_returns_false(self, run_dir, config):
        state = make_state(stage="drafted")
        state.pipeline.parked_reason = "blocked"
        save_change(run_dir / "change.md", state, "body")
        assert push_verify.verify(run_dir, config) is False

    def test_wrong_pre_state_returns_false(self, run_dir, config):
        state = make_state(stage="reviewed")
        save_change(run_dir / "change.md", state, "body")
        assert push_verify.verify(run_dir, config) is False


class TestPushVerifyHappyPath:
    @patch.object(push_verify, "repo_root")
    @patch.object(push_verify, "current_branch")
    @patch.object(push_verify, "commit")
    @patch.object(push_verify, "git_push")
    def test_commit_and_push_succeeds(
        self,
        mock_push,
        mock_commit,
        mock_branch,
        mock_root,
        run_dir,
        config,
    ):
        mock_root.return_value = run_dir
        mock_commit.return_value = "abc1234"
        mock_branch.return_value = "forger/test-001"

        state = make_state(stage="drafted")
        save_change(run_dir / "change.md", state, "body")
        _write_commit_file(run_dir)

        assert push_verify.verify(run_dir, config) is True

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.stage == "pushed"
        assert reloaded.github.branch == "forger/test-001"


class TestPushVerifyFailure:
    @patch.object(push_verify, "repo_root")
    @patch.object(push_verify, "current_branch")
    @patch.object(push_verify, "commit")
    @patch.object(push_verify, "git_push")
    def test_push_failure_parks(
        self,
        mock_push,
        mock_commit,
        mock_branch,
        mock_root,
        run_dir,
        config,
    ):
        mock_root.return_value = run_dir
        mock_commit.return_value = "abc1234"
        mock_branch.return_value = "forger/test-001"
        mock_push.side_effect = RuntimeError("git push failed: permission denied")

        state = make_state(stage="drafted")
        save_change(run_dir / "change.md", state, "body")
        _write_commit_file(run_dir)

        assert push_verify.verify(run_dir, config) is False

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.parked_reason is not None
        assert "push" in reloaded.pipeline.parked_reason.lower()

    @patch.object(push_verify, "repo_root")
    @patch.object(push_verify, "current_branch")
    @patch.object(push_verify, "commit")
    @patch.object(push_verify, "git_push")
    def test_commit_failure_parks(
        self,
        mock_push,
        mock_commit,
        mock_branch,
        mock_root,
        run_dir,
        config,
    ):
        mock_root.return_value = run_dir
        mock_commit.side_effect = RuntimeError("git add failed")
        mock_branch.return_value = "forger/test-001"

        state = make_state(stage="drafted")
        save_change(run_dir / "change.md", state, "body")
        _write_commit_file(run_dir)

        assert push_verify.verify(run_dir, config) is False

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.parked_reason is not None
        assert "commit" in reloaded.pipeline.parked_reason.lower()

    @patch.object(push_verify, "repo_root")
    @patch.object(push_verify, "current_branch")
    @patch.object(push_verify, "commit")
    @patch.object(push_verify, "git_push")
    def test_nothing_to_commit_still_pushes(
        self,
        mock_push,
        mock_commit,
        mock_branch,
        mock_root,
        run_dir,
        config,
    ):
        mock_root.return_value = run_dir
        mock_commit.return_value = None
        mock_branch.return_value = "forger/test-001"

        state = make_state(stage="drafted")
        save_change(run_dir / "change.md", state, "body")
        _write_commit_file(run_dir)

        assert push_verify.verify(run_dir, config) is True

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.stage == "pushed"


class TestPushVerifyGhAccount:
    @patch.object(push_verify, "repo_root")
    @patch.object(push_verify, "current_branch")
    @patch.object(push_verify, "commit")
    @patch.object(push_verify, "git_push")
    @patch.object(push_verify, "switch_gh_account")
    def test_switches_gh_account_when_configured(
        self,
        mock_switch,
        mock_push,
        mock_commit,
        mock_branch,
        mock_root,
        run_dir,
        config,
    ):
        config.gh_account = "my-org"
        mock_root.return_value = run_dir
        mock_commit.return_value = None
        mock_branch.return_value = "forger/test-001"

        state = make_state(stage="drafted")
        save_change(run_dir / "change.md", state, "body")
        _write_commit_file(run_dir)

        assert push_verify.verify(run_dir, config) is True

        mock_switch.assert_called_once_with("my-org", run_dir)
