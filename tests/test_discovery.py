"""Tests for TUI run discovery and status detection."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from forger.state import ChangeState, PipelineState, save_change
from forger.tui.discovery import (
    RunStatus,
    acquire_lock,
    discover_runs,
    is_lock_held,
    lock_path_for,
)


def _make_run(
    project_dir: Path,
    source: str,
    issue_id: str,
    stage: str = "triaged",
    parked_reason: str | None = None,
    with_events: bool = False,
    title: str | None = None,
) -> Path:
    """Create a run directory with change.md."""
    run_dir = project_dir / ".forger" / "artifacts" / source / f"run-{issue_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    state = ChangeState(
        id=f"{source}-{issue_id}",
        title=title or f"Test bug {issue_id}",
        origin=source,
        created="2026-08-02",
        updated="2026-08-02",
        pipeline=PipelineState(stage=stage, parked_reason=parked_reason),
    )
    save_change(run_dir / "change.md", state, "Test body.")
    if with_events:
        (run_dir / "events.jsonl").write_text("")
    return run_dir


class TestLockAcquireRelease:
    def test_acquire_creates_lock_file(self, tmp_path: Path):
        fd = acquire_lock("PROJ-1", tmp_path)
        try:
            assert lock_path_for("PROJ-1", tmp_path).exists()
        finally:
            os.close(fd)

    def test_acquire_writes_pid(self, tmp_path: Path):
        fd = acquire_lock("PROJ-2", tmp_path)
        try:
            content = lock_path_for("PROJ-2", tmp_path).read_text()
            assert str(os.getpid()) in content
        finally:
            os.close(fd)

    def test_acquire_twice_raises(self, tmp_path: Path):
        fd = acquire_lock("PROJ-3", tmp_path)
        try:
            with pytest.raises(OSError):
                acquire_lock("PROJ-3", tmp_path)
        finally:
            os.close(fd)

    def test_release_allows_reacquire(self, tmp_path: Path):
        fd = acquire_lock("PROJ-4", tmp_path)
        os.close(fd)
        fd2 = acquire_lock("PROJ-4", tmp_path)
        os.close(fd2)

    def test_creates_locks_dir(self, tmp_path: Path):
        fd = acquire_lock("PROJ-5", tmp_path)
        try:
            assert (tmp_path / ".forger" / "locks").is_dir()
        finally:
            os.close(fd)


class TestIsLockHeld:
    def test_no_lock_file(self, tmp_path: Path):
        assert is_lock_held("PROJ-1", tmp_path) is False

    def test_lock_held(self, tmp_path: Path):
        fd = acquire_lock("PROJ-2", tmp_path)
        try:
            assert is_lock_held("PROJ-2", tmp_path) is True
        finally:
            os.close(fd)

    def test_lock_released(self, tmp_path: Path):
        fd = acquire_lock("PROJ-3", tmp_path)
        os.close(fd)
        assert is_lock_held("PROJ-3", tmp_path) is False


class TestStatusDetection:
    """Test the full discover_runs() status logic against the decision #10 table."""

    def test_running(self, tmp_path: Path):
        """lock held + non-terminal + no parked → RUNNING"""
        _make_run(tmp_path, "sentry", "PROJ-1", stage="triaged")
        fd = acquire_lock("PROJ-1", tmp_path)
        try:
            runs = discover_runs(tmp_path)
            assert len(runs) == 1
            assert runs[0].status == RunStatus.RUNNING
        finally:
            os.close(fd)

    def test_blocked(self, tmp_path: Path):
        """lock held + parked → BLOCKED"""
        _make_run(
            tmp_path,
            "sentry",
            "PROJ-2",
            stage="proven",
            parked_reason="Gate fix_choice unresolved",
        )
        fd = acquire_lock("PROJ-2", tmp_path)
        try:
            runs = discover_runs(tmp_path)
            assert len(runs) == 1
            assert runs[0].status == RunStatus.BLOCKED
            assert runs[0].parked_reason is not None
        finally:
            os.close(fd)

    def test_completed(self, tmp_path: Path):
        """no lock + terminal stage → COMPLETED"""
        _make_run(tmp_path, "sentry", "PROJ-3", stage="pr-open")
        runs = discover_runs(tmp_path)
        assert len(runs) == 1
        assert runs[0].status == RunStatus.COMPLETED

    def test_crashed(self, tmp_path: Path):
        """no lock + non-terminal + no parked → CRASHED"""
        _make_run(tmp_path, "sentry", "PROJ-4", stage="analyzed")
        runs = discover_runs(tmp_path)
        assert len(runs) == 1
        assert runs[0].status == RunStatus.CRASHED

    def test_needs_attention(self, tmp_path: Path):
        """no lock + non-terminal + parked → NEEDS_ATTENTION"""
        _make_run(
            tmp_path,
            "sentry",
            "PROJ-5",
            stage="proven",
            parked_reason="Gate fix_choice unresolved",
        )
        runs = discover_runs(tmp_path)
        assert len(runs) == 1
        assert runs[0].status == RunStatus.NEEDS_ATTENTION


class TestDiscoverRuns:
    def test_no_artifacts_dir(self, tmp_path: Path):
        assert discover_runs(tmp_path) == []

    def test_empty_artifacts(self, tmp_path: Path):
        (tmp_path / ".forger" / "artifacts").mkdir(parents=True)
        assert discover_runs(tmp_path) == []

    def test_multiple_runs(self, tmp_path: Path):
        _make_run(tmp_path, "sentry", "PROJ-1", stage="triaged")
        _make_run(tmp_path, "sentry", "PROJ-2", stage="pr-open")
        runs = discover_runs(tmp_path)
        assert len(runs) == 2

    def test_sorted_by_source_then_id(self, tmp_path: Path):
        _make_run(tmp_path, "sentry", "B-2", stage="triaged")
        _make_run(tmp_path, "github", "A-1", stage="triaged")
        _make_run(tmp_path, "sentry", "A-1", stage="triaged")
        runs = discover_runs(tmp_path)
        sources = [(r.source, r.issue_id) for r in runs]
        assert sources == [("github", "A-1"), ("sentry", "A-1"), ("sentry", "B-2")]

    def test_skips_archive(self, tmp_path: Path):
        _make_run(tmp_path, "sentry", "PROJ-1", stage="triaged")
        archive = tmp_path / ".forger" / "artifacts" / "sentry" / "archive" / "run-OLD"
        archive.mkdir(parents=True)
        state = ChangeState(
            id="sentry-OLD",
            title="Old",
            origin="sentry",
            pipeline=PipelineState(stage="pr-open"),
        )
        save_change(archive / "change.md", state, "")
        runs = discover_runs(tmp_path)
        assert len(runs) == 1
        assert runs[0].issue_id == "PROJ-1"

    def test_has_events_flag(self, tmp_path: Path):
        _make_run(tmp_path, "sentry", "PROJ-1", stage="triaged", with_events=True)
        _make_run(tmp_path, "sentry", "PROJ-2", stage="triaged", with_events=False)
        runs = discover_runs(tmp_path)
        by_id = {r.issue_id: r for r in runs}
        assert by_id["PROJ-1"].has_events is True
        assert by_id["PROJ-2"].has_events is False

    def test_run_info_fields(self, tmp_path: Path):
        _make_run(
            tmp_path,
            "sentry",
            "PROJ-1",
            stage="analyzed",
            title="Fix auth bug",
        )
        runs = discover_runs(tmp_path)
        r = runs[0]
        assert r.issue_id == "PROJ-1"
        assert r.source == "sentry"
        assert r.stage == "analyzed"
        assert r.title == "Fix auth bug"
        assert r.run_dir.name == "run-PROJ-1"

    def test_skips_dirs_without_change_md(self, tmp_path: Path):
        artifacts = tmp_path / ".forger" / "artifacts" / "sentry" / "run-EMPTY"
        artifacts.mkdir(parents=True)
        assert discover_runs(tmp_path) == []

    def test_skips_corrupt_change_md(self, tmp_path: Path):
        run_dir = tmp_path / ".forger" / "artifacts" / "sentry" / "run-BAD"
        run_dir.mkdir(parents=True)
        (run_dir / "change.md").write_text("not valid frontmatter {{{{")
        assert discover_runs(tmp_path) == []


class TestRunInfoStageIndex:
    def test_known_stage(self, tmp_path: Path):
        _make_run(tmp_path, "sentry", "P-1", stage="triaged")
        runs = discover_runs(tmp_path)
        assert runs[0].stage_index == 0  # sentry_intake maps to index 0

    def test_terminal_stage(self, tmp_path: Path):
        _make_run(tmp_path, "sentry", "P-2", stage="pr-open")
        runs = discover_runs(tmp_path)
        assert runs[0].stage_index == 7  # push is last stage

    def test_unknown_stage(self, tmp_path: Path):
        _make_run(tmp_path, "sentry", "P-3", stage="some-weird-state")
        runs = discover_runs(tmp_path)
        assert runs[0].stage_index == -1
