"""Tests for push/verify.py — commit, push, issue, PR orchestration."""

from pathlib import Path
from unittest.mock import patch

import pytest

import forger.stages.push.verify as push_verify
from forger.state import (
    GithubState,
    load_change,
    save_change,
)
from tests import make_state


@pytest.fixture
def run_dir(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    return d


def _write_deliverables(run_dir: Path):
    (run_dir / "commit.txt").write_text("fix: resolve bug")
    (run_dir / "issue.md").write_text("# Bug fix\nDetails.")
    (run_dir / "pr.md").write_text("# Fix bug\n\nCloses #<issue-number>\n\nPR body.")


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
    @patch.object(push_verify, "create_issue")
    @patch.object(push_verify, "create_pr")
    def test_full_push_succeeds(
        self,
        mock_create_pr,
        mock_create_issue,
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
        mock_create_issue.return_value = "https://github.com/org/repo/issues/1"
        mock_create_pr.return_value = "https://github.com/org/repo/pull/1"

        state = make_state(stage="drafted")
        save_change(run_dir / "change.md", state, "body")
        _write_deliverables(run_dir)

        assert push_verify.verify(run_dir, config) is True

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.stage == "pr-open"
        assert reloaded.github.pr == "https://github.com/org/repo/pull/1"
        assert reloaded.github.issue == "https://github.com/org/repo/issues/1"
        assert reloaded.github.branch == "forger/test-001"


class TestIssueNumberSubstitution:
    @patch.object(push_verify, "repo_root")
    @patch.object(push_verify, "current_branch")
    @patch.object(push_verify, "commit")
    @patch.object(push_verify, "git_push")
    @patch.object(push_verify, "create_issue")
    @patch.object(push_verify, "create_pr")
    def test_substitutes_issue_number_in_pr_body(
        self,
        mock_create_pr,
        mock_create_issue,
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
        mock_create_issue.return_value = "https://github.com/org/repo/issues/42"
        mock_create_pr.return_value = "https://github.com/org/repo/pull/1"

        state = make_state(stage="drafted")
        save_change(run_dir / "change.md", state, "body")
        _write_deliverables(run_dir)

        assert push_verify.verify(run_dir, config) is True

        pr_content = (run_dir / "pr.md").read_text()
        assert "Closes #42" in pr_content
        assert "#<issue-number>" not in pr_content


class TestPushVerifyPartialFailure:
    @patch.object(push_verify, "repo_root")
    @patch.object(push_verify, "current_branch")
    @patch.object(push_verify, "commit")
    @patch.object(push_verify, "git_push")
    @patch.object(push_verify, "create_issue")
    @patch.object(push_verify, "create_pr")
    def test_push_failure_parks_with_partial_progress(
        self,
        mock_create_pr,
        mock_create_issue,
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
        mock_create_issue.return_value = "https://github.com/org/repo/issues/1"
        mock_create_pr.return_value = "https://github.com/org/repo/pull/1"

        state = make_state(stage="drafted")
        save_change(run_dir / "change.md", state, "body")
        _write_deliverables(run_dir)

        assert push_verify.verify(run_dir, config) is False

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.parked_reason is not None
        assert "push" in reloaded.pipeline.parked_reason.lower()

    @patch.object(push_verify, "repo_root")
    @patch.object(push_verify, "current_branch")
    @patch.object(push_verify, "commit")
    @patch.object(push_verify, "git_push")
    @patch.object(push_verify, "create_issue")
    @patch.object(push_verify, "create_pr")
    def test_commit_failure_parks(
        self,
        mock_create_pr,
        mock_create_issue,
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
        mock_create_issue.return_value = "https://github.com/org/repo/issues/1"
        mock_create_pr.return_value = "https://github.com/org/repo/pull/1"

        state = make_state(stage="drafted")
        save_change(run_dir / "change.md", state, "body")
        _write_deliverables(run_dir)

        assert push_verify.verify(run_dir, config) is False

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.parked_reason is not None
        assert "commit" in reloaded.pipeline.parked_reason.lower()

    @patch.object(push_verify, "repo_root")
    @patch.object(push_verify, "current_branch")
    @patch.object(push_verify, "commit")
    @patch.object(push_verify, "git_push")
    @patch.object(push_verify, "create_issue")
    @patch.object(push_verify, "create_pr")
    def test_nothing_to_commit_still_pushes(
        self,
        mock_create_pr,
        mock_create_issue,
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
        mock_create_issue.return_value = "https://github.com/org/repo/issues/1"
        mock_create_pr.return_value = "https://github.com/org/repo/pull/1"

        state = make_state(stage="drafted")
        save_change(run_dir / "change.md", state, "body")
        _write_deliverables(run_dir)

        assert push_verify.verify(run_dir, config) is True

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.stage == "pr-open"


class TestPushVerifyIdempotency:
    @patch.object(push_verify, "repo_root")
    @patch.object(push_verify, "current_branch")
    @patch.object(push_verify, "commit")
    @patch.object(push_verify, "git_push")
    @patch.object(push_verify, "create_issue")
    @patch.object(push_verify, "create_pr")
    def test_skips_existing_issue_and_pr(
        self,
        mock_create_pr,
        mock_create_issue,
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

        state = make_state(
            stage="drafted",
            github=GithubState(
                issue="https://github.com/org/repo/issues/1",
                pr="https://github.com/org/repo/pull/1",
            ),
        )
        save_change(run_dir / "change.md", state, "body")
        _write_deliverables(run_dir)

        assert push_verify.verify(run_dir, config) is True

        mock_create_issue.assert_not_called()
        mock_create_pr.assert_not_called()


class TestPushVerifyGhAccount:
    @patch.object(push_verify, "repo_root")
    @patch.object(push_verify, "current_branch")
    @patch.object(push_verify, "commit")
    @patch.object(push_verify, "git_push")
    @patch.object(push_verify, "create_issue")
    @patch.object(push_verify, "create_pr")
    @patch.object(push_verify, "switch_gh_account")
    def test_switches_gh_account_when_configured(
        self,
        mock_switch,
        mock_create_pr,
        mock_create_issue,
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
        mock_create_issue.return_value = "https://github.com/org/repo/issues/1"
        mock_create_pr.return_value = "https://github.com/org/repo/pull/1"

        state = make_state(stage="drafted")
        save_change(run_dir / "change.md", state, "body")
        _write_deliverables(run_dir)

        assert push_verify.verify(run_dir, config) is True

        mock_switch.assert_called_once_with("my-org", run_dir)
