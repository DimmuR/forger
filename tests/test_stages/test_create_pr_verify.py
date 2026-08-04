"""Tests for create_pr/verify.py — GitHub PR creation."""

from pathlib import Path
from unittest.mock import patch

import pytest

import forger.stages.create_pr.verify as create_pr_verify
from forger.state import GithubState, load_change, save_change
from tests import make_state


@pytest.fixture
def run_dir(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    return d


def _write_pr_file(
    run_dir: Path, content: str = "# Fix bug\n\nCloses #<issue-number>\n\nPR body."
):
    (run_dir / "pr.md").write_text(content)


class TestCreatePrGuards:
    def test_wrong_pre_state_returns_false(self, run_dir, config):
        state = make_state(stage="pushed")
        save_change(run_dir / "change.md", state, "body")
        assert create_pr_verify.verify(run_dir, config) is False

    def test_parked_returns_false(self, run_dir, config):
        state = make_state(stage="issue-created")
        state.pipeline.parked_reason = "blocked"
        save_change(run_dir / "change.md", state, "body")
        assert create_pr_verify.verify(run_dir, config) is False


class TestCreatePrHappyPath:
    @patch.object(create_pr_verify, "repo_root")
    @patch.object(create_pr_verify, "create_pr")
    def test_creates_pr(self, mock_create_pr, mock_root, run_dir, config):
        mock_root.return_value = run_dir
        mock_create_pr.return_value = "https://github.com/org/repo/pull/1"

        state = make_state(
            stage="issue-created",
            github=GithubState(issue="https://github.com/org/repo/issues/42"),
        )
        save_change(run_dir / "change.md", state, "body")
        _write_pr_file(run_dir)

        assert create_pr_verify.verify(run_dir, config) is True

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.stage == "pr-open"
        assert reloaded.github.pr == "https://github.com/org/repo/pull/1"


class TestIssueNumberSubstitution:
    @patch.object(create_pr_verify, "repo_root")
    @patch.object(create_pr_verify, "create_pr")
    def test_substitutes_issue_number(self, mock_create_pr, mock_root, run_dir, config):
        mock_root.return_value = run_dir
        mock_create_pr.return_value = "https://github.com/org/repo/pull/1"

        state = make_state(
            stage="issue-created",
            github=GithubState(issue="https://github.com/org/repo/issues/42"),
        )
        save_change(run_dir / "change.md", state, "body")
        _write_pr_file(run_dir)

        assert create_pr_verify.verify(run_dir, config) is True

        pr_content = (run_dir / "pr.md").read_text()
        assert "Closes #42" in pr_content
        assert "#<issue-number>" not in pr_content


class TestCreatePrIdempotency:
    def test_skips_when_pr_exists(self, run_dir, config):
        state = make_state(
            stage="issue-created",
            github=GithubState(
                issue="https://github.com/org/repo/issues/1",
                pr="https://github.com/org/repo/pull/1",
            ),
        )
        save_change(run_dir / "change.md", state, "body")

        assert create_pr_verify.verify(run_dir, config) is True

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.stage == "pr-open"


class TestCreatePrFailure:
    def test_missing_pr_md_parks(self, run_dir, config):
        state = make_state(stage="issue-created")
        save_change(run_dir / "change.md", state, "body")

        assert create_pr_verify.verify(run_dir, config) is False

        reloaded, _ = load_change(run_dir / "change.md")
        assert "pr.md" in reloaded.pipeline.parked_reason

    @patch.object(create_pr_verify, "repo_root")
    @patch.object(create_pr_verify, "create_pr")
    def test_api_failure_parks(self, mock_create_pr, mock_root, run_dir, config):
        mock_root.return_value = run_dir
        mock_create_pr.side_effect = RuntimeError("API error")

        state = make_state(stage="issue-created")
        save_change(run_dir / "change.md", state, "body")
        _write_pr_file(run_dir)

        assert create_pr_verify.verify(run_dir, config) is False

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.parked_reason is not None
