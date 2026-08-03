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
    STOPPING = "stopping"  # ephemeral UI-only state, never from _determine_status
    BLOCKED = "blocked"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"
    CRASHED = "crashed"
    NEEDS_ATTENTION = "needs_attention"
    SCHEDULED = "scheduled"
    MISSED = "missed"


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
    fire_at: datetime | None = None

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
    stage: str,
    parked_reason: str | None,
    lock_held: bool,
    exit_type: str | None = None,
) -> RunStatus:
    """Derive run status from lock state, pipeline state, and exit type.

    exit_type comes from events.jsonl:
      "stopped"  → user stopped via TUI
      "ended"    → process exited gracefully (pipeline_end emitted)
      None       → no terminal event (process died abruptly)
    """
    is_terminal = stage in TERMINAL_STAGES

    if lock_held:
        if parked_reason:
            return RunStatus.BLOCKED
        return RunStatus.RUNNING

    if is_terminal:
        return RunStatus.COMPLETED

    if exit_type == "stopped":
        return RunStatus.STOPPED

    if parked_reason:
        return RunStatus.NEEDS_ATTENTION

    if exit_type == "ended":
        return RunStatus.FAILED

    return RunStatus.CRASHED


def _parse_ts(raw: str) -> datetime | None:
    """Parse ISO 8601 timestamp from events.jsonl."""
    try:
        raw = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class _EventSummary:
    started_at: datetime | None = None
    ended_at: datetime | None = None
    exit_type: str | None = None
    fire_at: datetime | None = None
    is_scheduled: bool = False
    schedule_cancelled: bool = False


def _read_event_summary(events_path: Path) -> _EventSummary:
    """Extract timestamps and exit type from events.jsonl.

    exit_type: "stopped" if pipeline_stopped found, "ended" if pipeline_end
    found, None if neither (abrupt death).
    """
    if not events_path.exists():
        return _EventSummary()

    started_at: datetime | None = None
    ended_at: datetime | None = None
    exit_type: str | None = None
    fire_at: datetime | None = None
    is_scheduled: bool = False
    schedule_cancelled: bool = False

    try:
        with open(events_path) as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                ev = json.loads(stripped)
                ev_type = ev.get("type")
                if ev_type == "pipeline_start":
                    started_at = _parse_ts(ev.get("ts", ""))
                    ended_at = None
                    exit_type = None
                elif ev_type == "pipeline_stopped":
                    exit_type = "stopped"
                elif ev_type == "pipeline_end":
                    ended_at = _parse_ts(ev.get("ts", ""))
                    if exit_type != "stopped":
                        exit_type = "ended"
                elif ev_type == "pipeline_scheduled":
                    fire_at = _parse_ts(ev.get("fire_at", ""))
                    is_scheduled = True
                    schedule_cancelled = False
                elif ev_type == "pipeline_schedule_cancelled":
                    schedule_cancelled = True
    except (json.JSONDecodeError, OSError):
        pass

    return _EventSummary(
        started_at=started_at,
        ended_at=ended_at,
        exit_type=exit_type,
        fire_at=fire_at,
        is_scheduled=is_scheduled,
        schedule_cancelled=schedule_cancelled,
    )


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
            source = source_dir.name

            # Derive bare issue_id from directory name (run-<id> → <id>)
            dir_name = run_dir.name
            bare_id = dir_name[4:] if dir_name.startswith("run-") else dir_name

            if not change_path.exists():
                events_path = run_dir / "events.jsonl"
                ev = _read_event_summary(events_path)

                # Scheduled run: no change.md yet, has pipeline_scheduled event
                if ev.is_scheduled and not ev.schedule_cancelled and not ev.started_at:
                    now = datetime.now(UTC)
                    if ev.fire_at and ev.fire_at > now:
                        sched_status = RunStatus.SCHEDULED
                    else:
                        sched_status = RunStatus.MISSED
                    runs.append(
                        RunInfo(
                            issue_id=bare_id,
                            source=source,
                            stage="scheduled",
                            status=sched_status,
                            title=bare_id,
                            run_dir=run_dir,
                            has_events=True,
                            fire_at=ev.fire_at,
                        )
                    )
                    continue

                # No change.md yet — visible only if lock held (intake in progress)
                if not is_lock_held(bare_id, project_dir):
                    continue

                runs.append(
                    RunInfo(
                        issue_id=bare_id,
                        source=source,
                        stage="intake",
                        status=RunStatus.RUNNING,
                        title=bare_id,
                        run_dir=run_dir,
                        has_events=events_path.exists(),
                        started_at=ev.started_at,
                        ended_at=ev.ended_at,
                    )
                )
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

            # Check both canonical and worktree for events
            events_path = run_dir / "events.jsonl"
            if wt_path:
                wt_events = worktree.worktree_run_dir(wt_path) / "events.jsonl"
                if wt_events.exists():
                    events_path = wt_events
            ev = _read_event_summary(events_path)

            status = _determine_status(
                state.pipeline.stage,
                state.pipeline.parked_reason,
                lock_held,
                ev.exit_type,
            )

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
                    started_at=ev.started_at,
                    ended_at=ev.ended_at,
                )
            )

    # Most recent first; runs without timestamps sort last
    _epoch = datetime.min.replace(tzinfo=UTC)
    runs.sort(key=lambda r: r.started_at or r.fire_at or _epoch, reverse=True)
    return runs
