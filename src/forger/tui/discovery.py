"""Run discovery and status detection for the TUI dashboard.

Scans .forger/artifacts/ for runs and uses fcntl locks to determine
whether each run's process is still alive.
"""

from __future__ import annotations

import fcntl
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from forger import worktree
from forger.pipeline import STAGES
from forger.state import TERMINAL_STAGES, load_change


class RunStatus(Enum):
    """Observable run status derived from lock + pipeline state."""

    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CRASHED = "crashed"
    NEEDS_ATTENTION = "needs_attention"


@dataclass(frozen=True)
class RunInfo:
    """Snapshot of a single pipeline run's state."""

    issue_id: str
    source: str
    stage: str
    status: RunStatus
    title: str
    run_dir: Path
    parked_reason: str | None = None
    has_events: bool = False
    started_at: datetime | None = None
    ended_at: datetime | None = None

    @property
    def stage_index(self) -> int:
        """0-based index of current stage in pipeline, -1 if unknown."""
        for i, spec in enumerate(STAGES):
            if self.stage in (spec.name, spec.post_state, spec.pre_state):
                return i
        return -1


def _locks_dir(project_dir: Path) -> Path:
    return project_dir / ".forger" / "locks"


def lock_path_for(issue_id: str, project_dir: Path) -> Path:
    """Return the lock file path for a given run."""
    return _locks_dir(project_dir) / f"run-{issue_id}.lock"


def acquire_lock(issue_id: str, project_dir: Path) -> int:
    """Acquire exclusive fcntl lock for a run. Returns the fd.

    The lock is held until the fd is closed (process exit releases it).
    Caller should store the fd and keep it open for the run's lifetime.
    """
    locks_dir = _locks_dir(project_dir)
    locks_dir.mkdir(parents=True, exist_ok=True)

    path = lock_path_for(issue_id, project_dir)
    import os

    fd = os.open(str(path), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        raise
    os.write(fd, f"{os.getpid()}\n".encode())
    os.fsync(fd)
    return fd


def is_lock_held(issue_id: str, project_dir: Path) -> bool:
    """Check if a run's lock is currently held by another process.

    Non-destructive: if lock is free, acquires and immediately releases.
    """
    path = lock_path_for(issue_id, project_dir)
    if not path.exists():
        return False

    import os

    fd = os.open(str(path), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Got the lock → not held by anyone
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        # Lock held by another process
        return True
    finally:
        os.close(fd)


def _determine_status(
    stage: str, parked_reason: str | None, lock_held: bool
) -> RunStatus:
    """Derive run status from lock state and pipeline state.

    Logic table from decision #10:
      lock_held  terminal  parked  → status
      yes        no        no      → RUNNING
      yes        no        yes     → BLOCKED
      no         yes       —       → COMPLETED
      no         no        no      → CRASHED
      no         no        yes     → NEEDS_ATTENTION
    """
    is_terminal = stage in TERMINAL_STAGES

    if lock_held:
        if parked_reason:
            return RunStatus.BLOCKED
        return RunStatus.RUNNING

    if is_terminal:
        return RunStatus.COMPLETED

    if parked_reason:
        return RunStatus.NEEDS_ATTENTION
    return RunStatus.CRASHED


def _parse_ts(raw: str) -> datetime | None:
    """Parse ISO 8601 timestamp from events.jsonl."""
    try:
        raw = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


def _read_event_timestamps(
    events_path: Path,
) -> tuple[datetime | None, datetime | None]:
    """Extract start and end timestamps from events.jsonl.

    Reads first line for pipeline_start ts, last line for pipeline_end ts.
    """
    if not events_path.exists():
        return None, None

    started_at: datetime | None = None
    ended_at: datetime | None = None

    try:
        with open(events_path) as f:
            first_line = f.readline().strip()
            if first_line:
                ev = json.loads(first_line)
                if ev.get("type") == "pipeline_start":
                    started_at = _parse_ts(ev.get("ts", ""))

            last_line = first_line
            for line in f:
                stripped = line.strip()
                if stripped:
                    last_line = stripped

            if last_line and last_line != first_line:
                ev = json.loads(last_line)
                if ev.get("type") == "pipeline_end":
                    ended_at = _parse_ts(ev.get("ts", ""))
    except (json.JSONDecodeError, OSError):
        pass

    return started_at, ended_at


def discover_runs(project_dir: Path) -> list[RunInfo]:
    """Scan .forger/artifacts/ for all runs and their status.

    Returns list sorted by source then issue_id.
    """
    artifacts_dir = project_dir / ".forger" / "artifacts"
    if not artifacts_dir.exists():
        return []

    runs: list[RunInfo] = []

    for source_dir in sorted(artifacts_dir.iterdir()):
        if not source_dir.is_dir() or source_dir.name == "archive":
            continue

        for run_dir in sorted(source_dir.iterdir()):
            if run_dir.name == "archive" or not run_dir.is_dir():
                continue

            change_path = run_dir / "change.md"
            if not change_path.exists():
                continue

            try:
                state, _ = load_change(change_path)
            except Exception:
                continue

            issue_id = state.id
            # Strip source prefix if present (e.g. "sentry-PROJ-123" → "PROJ-123")
            bare_id = issue_id
            if issue_id.startswith(f"{state.origin}-"):
                bare_id = issue_id[len(state.origin) + 1 :]

            # Prefer worktree change.md if worktree is active
            wt_path = worktree.path_for(bare_id, project_dir)
            if wt_path:
                wt_change = worktree.worktree_run_dir(wt_path) / "change.md"
                if wt_change.exists():
                    import contextlib

                    with contextlib.suppress(Exception):
                        state, _ = load_change(wt_change)

            lock_held = is_lock_held(bare_id, project_dir)
            status = _determine_status(
                state.pipeline.stage, state.pipeline.parked_reason, lock_held
            )

            # Check both canonical and worktree for events
            events_path = run_dir / "events.jsonl"
            if wt_path:
                wt_events = worktree.worktree_run_dir(wt_path) / "events.jsonl"
                if wt_events.exists():
                    events_path = wt_events
            started_at, ended_at = _read_event_timestamps(events_path)

            runs.append(
                RunInfo(
                    issue_id=bare_id,
                    source=state.origin,
                    stage=state.pipeline.stage,
                    status=status,
                    title=state.title,
                    run_dir=run_dir,
                    parked_reason=state.pipeline.parked_reason,
                    has_events=events_path.exists()
                    or (run_dir / "events.jsonl").exists(),
                    started_at=started_at,
                    ended_at=ended_at,
                )
            )

    # Most recent first; runs without timestamps sort last
    _epoch = datetime.min.replace(tzinfo=UTC)
    runs.sort(key=lambda r: r.started_at or _epoch, reverse=True)
    return runs
