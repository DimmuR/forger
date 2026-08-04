"""Tests for create_issue/verify.py — GitHub issue creation."""

from pathlib import Path
from unittest.mock import patch

import pytest

import forger.stages.create_issue.verify as create_issue_verify
from forger.state import GithubState, load_change, save_change
from tests import make_state


@pytest.fixture
def run_dir(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    return d


def _write_issue_file(run_dir: Path):
    (run_dir / "issue.md").write_text("# Bug fix\nDetails.")


class TestCreateIssueGuards:
    def test_wrong_pre_state_returns_false(self, run_dir, config):
        state = make_state(stage="drafted")
        save_change(run_dir / "change.md", state, "body")
        assert create_issue_verify.verify(run_dir, config) is False

    def test_parked_returns_false(self, run_dir, config):
        state = make_state(stage="pushed")
        state.pipeline.parked_reason = "blocked"
        save_change(run_dir / "change.md", state, "body")
        assert create_issue_verify.verify(run_dir, config) is False


class TestCreateIssueHappyPath:
    @patch.object(create_issue_verify, "repo_root")
    @patch.object(create_issue_verify, "create_issue")
    def test_creates_issue(self, mock_create_issue, mock_root, run_dir, config):
        mock_root.return_value = run_dir
        mock_create_issue.return_value = "https://github.com/org/repo/issues/42"

        state = make_state(stage="pushed")
        save_change(run_dir / "change.md", state, "body")
        _write_issue_file(run_dir)

        assert create_issue_verify.verify(run_dir, config) is True

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.stage == "issue-created"
        assert reloaded.github.issue == "https://github.com/org/repo/issues/42"


class TestCreateIssueIdempotency:
    def test_skips_when_issue_exists(self, run_dir, config):
        state = make_state(
            stage="pushed",
            github=GithubState(issue="https://github.com/org/repo/issues/1"),
        )
        save_change(run_dir / "change.md", state, "body")

        assert create_issue_verify.verify(run_dir, config) is True

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.stage == "issue-created"


class TestCreateIssueFailure:
    def test_missing_issue_md_parks(self, run_dir, config):
        state = make_state(stage="pushed")
        save_change(run_dir / "change.md", state, "body")

        assert create_issue_verify.verify(run_dir, config) is False

        reloaded, _ = load_change(run_dir / "change.md")
        assert "issue.md" in reloaded.pipeline.parked_reason

    @patch.object(create_issue_verify, "repo_root")
    @patch.object(create_issue_verify, "create_issue")
    def test_api_failure_parks(self, mock_create_issue, mock_root, run_dir, config):
        mock_root.return_value = run_dir
        mock_create_issue.side_effect = RuntimeError("API error")

        state = make_state(stage="pushed")
        save_change(run_dir / "change.md", state, "body")
        _write_issue_file(run_dir)

        assert create_issue_verify.verify(run_dir, config) is False

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.parked_reason is not None
