"""Tests for create_patch/verify.py — export changes as patch file."""

import subprocess
from unittest.mock import patch

import pytest

import forger.stages.create_patch.verify as create_patch_verify
from forger.state import load_change, save_change
from tests import make_state


@pytest.fixture
def run_dir(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    return d


class TestCreatePatchGuards:
    def test_wrong_pre_state_returns_false(self, run_dir, config):
        state = make_state(stage="reviewed")
        save_change(run_dir / "change.md", state, "body")
        assert create_patch_verify.verify(run_dir, config) is False

    def test_parked_returns_false(self, run_dir, config):
        state = make_state(stage="drafted")
        state.pipeline.parked_reason = "blocked"
        save_change(run_dir / "change.md", state, "body")
        assert create_patch_verify.verify(run_dir, config) is False


class TestCreatePatchHappyPath:
    @patch.object(create_patch_verify, "repo_root")
    @patch("subprocess.run")
    def test_creates_patch_file(self, mock_run, mock_root, run_dir, config):
        mock_root.return_value = run_dir

        diff_output = "diff --git a/file.txt b/file.txt\n+new line\n"
        mock_run.side_effect = [
            subprocess.CompletedProcess([], 0),  # git add -A
            subprocess.CompletedProcess([], 0, stdout=diff_output),  # git diff
        ]

        state = make_state(stage="drafted")
        save_change(run_dir / "change.md", state, "body")

        assert create_patch_verify.verify(run_dir, config) is True

        reloaded, _ = load_change(run_dir / "change.md")
        assert reloaded.pipeline.stage == "patched"

        patch_file = run_dir / "sentry-TEST-001.patch"
        assert patch_file.exists()
        assert patch_file.read_text() == diff_output


class TestCreatePatchNoChanges:
    @patch.object(create_patch_verify, "repo_root")
    @patch("subprocess.run")
    def test_no_changes_parks(self, mock_run, mock_root, run_dir, config):
        mock_root.return_value = run_dir

        mock_run.side_effect = [
            subprocess.CompletedProcess([], 0),  # git add -A
            subprocess.CompletedProcess([], 0, stdout=""),  # git diff empty
        ]

        state = make_state(stage="drafted")
        save_change(run_dir / "change.md", state, "body")

        assert create_patch_verify.verify(run_dir, config) is False

        reloaded, _ = load_change(run_dir / "change.md")
        assert "no changes" in reloaded.pipeline.parked_reason.lower()
