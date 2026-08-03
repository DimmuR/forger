"""Shared run factories for TUI integration tests."""

from __future__ import annotations

from pathlib import Path

from forger.tui.discovery import acquire_lock


def make_tui_run(
    tmp_path: Path,
    issue_id: str = "TEST-1",
    *,
    source: str = "sentry",
    stage: str = "triaged",
    events_content: str | None = None,
) -> Path:
    """Create a minimal run directory with raw YAML change.md."""
    source_dir = tmp_path / ".forger" / "artifacts" / source
    run_dir = source_dir / f"run-{issue_id}"
    run_dir.mkdir(parents=True)
    (run_dir / "change.md").write_text(
        f"---\nid: {issue_id}\ntitle: test\norigin: {source}\n"
        f"pipeline:\n  stage: {stage}\n  parked_reason: null\n---\n"
    )
    if events_content is not None:
        (run_dir / "events.jsonl").write_text(events_content)
    return run_dir


def make_stopped_run(tmp_path: Path, issue_id: str = "TEST-1") -> Path:
    return make_tui_run(
        tmp_path,
        issue_id,
        events_content=(
            '{"type":"pipeline_start","ts":"2024-01-01T00:00:00Z"}\n'
            '{"type":"pipeline_stopped","reason":"user","ts":"2024-01-01T00:01:00Z"}\n'
        ),
    )


def make_crashed_run(tmp_path: Path, issue_id: str = "TEST-1") -> Path:
    return make_tui_run(
        tmp_path,
        issue_id,
        events_content='{"type":"pipeline_start","ts":"2024-01-01T00:00:00Z"}\n',
    )


def make_failed_run(tmp_path: Path, issue_id: str = "TEST-1") -> Path:
    return make_tui_run(
        tmp_path,
        issue_id,
        events_content=(
            '{"type":"pipeline_start","ts":"2024-01-01T00:00:00Z"}\n'
            '{"type":"pipeline_end","final_stage":"triaged","ts":"2024-01-01T00:01:00Z"}\n'
        ),
    )


def make_completed_run(tmp_path: Path, issue_id: str = "TEST-1") -> Path:
    return make_tui_run(tmp_path, issue_id, stage="pr-open")


def make_running_run(tmp_path: Path, issue_id: str = "TEST-1") -> tuple[Path, int]:
    """Returns (run_dir, lock_fd). Caller must os.close(fd)."""
    run_dir = make_tui_run(tmp_path, issue_id, stage="analyze")
    fd = acquire_lock(issue_id, tmp_path)
    return run_dir, fd
