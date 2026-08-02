"""Tests for CLI commands via Typer CliRunner."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from forger.cli import app
from forger.state import ChangeState, Gate, PipelineState, save_change

runner = CliRunner()


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """Fake project with .forger structure and git dir."""
    forger_dir = tmp_path / ".forger"
    forger_dir.mkdir()
    (forger_dir / "artifacts" / "sentry").mkdir(parents=True)
    (forger_dir / "config.yaml").write_text("commands:\n  test: pytest\n")
    git_dir = tmp_path / ".git" / "info"
    git_dir.mkdir(parents=True)
    (git_dir / "exclude").write_text("")
    monkeypatch.setattr("forger.cli._repo_dir", lambda: tmp_path)
    return tmp_path


def _make_run(project_dir: Path, source: str, issue_id: str, **pipeline_kwargs):
    """Create a run with change.md."""
    run_dir = project_dir / ".forger" / "artifacts" / source / f"run-{issue_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    state = ChangeState(
        id=f"{source}-{issue_id}",
        title=f"Test bug {issue_id}",
        origin=source,
        created="2026-07-18",
        updated="2026-07-18",
        pipeline=PipelineState(**pipeline_kwargs),
    )
    save_change(run_dir / "change.md", state, "Test body.")
    return run_dir


class TestInit:
    def test_creates_forger_dir(self, tmp_path, monkeypatch):
        git_dir = tmp_path / ".git" / "info"
        git_dir.mkdir(parents=True)
        (git_dir / "exclude").write_text("")
        monkeypatch.setattr("forger.cli._repo_dir", lambda: tmp_path)
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert (tmp_path / ".forger").exists()
        assert (tmp_path / ".forger" / "artifacts").exists()
        assert (tmp_path / ".forger" / "config.yaml").exists()

    def test_adds_to_git_exclude(self, tmp_path, monkeypatch):
        git_dir = tmp_path / ".git" / "info"
        git_dir.mkdir(parents=True)
        (git_dir / "exclude").write_text("some-other-thing\n")
        monkeypatch.setattr("forger.cli._repo_dir", lambda: tmp_path)
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert ".forger/" in (git_dir / "exclude").read_text()

    def test_already_initialized(self, project_dir):
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert "already exists" in result.stdout


class TestStatus:
    def test_no_runs(self, project_dir):
        # Remove artifacts dir to simulate fresh project
        import shutil

        shutil.rmtree(project_dir / ".forger" / "artifacts")
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "No runs found" in result.stdout

    def test_list_all_runs(self, project_dir):
        _make_run(project_dir, "sentry", "PROJ-001", stage="triaged")
        _make_run(project_dir, "sentry", "PROJ-002", stage="analyzed")
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "sentry-PROJ-001" in result.stdout
        assert "sentry-PROJ-002" in result.stdout
        assert "triaged" in result.stdout
        assert "analyzed" in result.stdout

    def test_single_run_detail(self, project_dir):
        _make_run(project_dir, "sentry", "PROJ-001", stage="triaged")
        result = runner.invoke(app, ["status", "PROJ-001"])
        assert result.exit_code == 0
        assert "Run:" in result.stdout
        assert "sentry-PROJ-001" in result.stdout
        assert "Title:" in result.stdout
        assert "Stage:" in result.stdout
        assert "triaged" in result.stdout

    def test_single_run_not_found(self, project_dir):
        result = runner.invoke(app, ["status", "NONEXISTENT"])
        assert result.exit_code == 1

    def test_parked_run_shows_reason(self, project_dir):
        _make_run(
            project_dir,
            "sentry",
            "PROJ-003",
            stage="analyzed",
            parked_reason="Cannot reproduce",
        )
        result = runner.invoke(app, ["status", "PROJ-003"])
        assert result.exit_code == 0
        assert "Cannot reproduce" in result.stdout

    def test_gates_displayed(self, project_dir):
        run_dir = _make_run(project_dir, "sentry", "PROJ-004", stage="proven")
        from forger.state import load_change

        state, body = load_change(run_dir / "change.md")
        state.gates["fix_choice"] = Gate(required=True, resolved=None)
        save_change(run_dir / "change.md", state, body)
        result = runner.invoke(app, ["status", "PROJ-004"])
        assert result.exit_code == 0
        assert "fix_choice" in result.stdout
        assert "UNRESOLVED" in result.stdout


class TestArchive:
    def test_archive_moves_run(self, project_dir):
        _make_run(project_dir, "sentry", "PROJ-001", stage="pr-open")
        result = runner.invoke(app, ["archive", "PROJ-001"])
        assert result.exit_code == 0
        assert "Archived" in result.stdout
        archive_dir = project_dir / ".forger" / "artifacts" / "sentry" / "archive"
        assert (archive_dir / "run-PROJ-001").exists()
        assert not (
            project_dir / ".forger" / "artifacts" / "sentry" / "run-PROJ-001"
        ).exists()

    def test_archive_not_found(self, project_dir):
        result = runner.invoke(app, ["archive", "NONEXISTENT"])
        assert result.exit_code == 1


class TestPrompt:
    def test_render_prompt(self, project_dir):
        _make_run(project_dir, "sentry", "PROJ-001", stage="triaged")
        result = runner.invoke(app, ["prompt", "PROJ-001"])
        assert result.exit_code == 0
        assert "Run Context" in result.stdout

    def test_prompt_not_found(self, project_dir):
        result = runner.invoke(app, ["prompt", "NONEXISTENT"])
        assert result.exit_code == 1

    def test_prompt_terminal_stage(self, project_dir):
        _make_run(project_dir, "sentry", "PROJ-001", stage="pr-open")
        result = runner.invoke(app, ["prompt", "PROJ-001"])
        assert result.exit_code == 1
