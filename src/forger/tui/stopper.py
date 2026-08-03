"""Stop a running pipeline by sending SIGTERM to its process group."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

from forger import worktree
from forger.events import format_event_ts
from forger.tui.discovery import is_lock_held, lock_path_for


def read_pid_from_lock(issue_id: str, project_dir: Path) -> int | None:
    """Read the PID stored in a run's lock file."""
    path = lock_path_for(issue_id, project_dir)
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError):
        return None


def _emit_stopped_event(issue_id: str, run_dir: Path, project_dir: Path) -> None:
    """Append pipeline_stopped event to events.jsonl.

    Writes to both canonical and worktree locations (if worktree active)
    so the event survives regardless of cleanup order.
    """
    record = json.dumps(
        {
            "ts": format_event_ts(),
            "type": "pipeline_stopped",
            "reason": "user",
        },
        separators=(",", ":"),
    )
    line = record + "\n"

    paths = [run_dir / "events.jsonl"]
    wt_path = worktree.path_for(issue_id, project_dir)
    if wt_path:
        wt_events = worktree.worktree_run_dir(wt_path) / "events.jsonl"
        if wt_events.exists():
            paths.append(wt_events)

    for path in paths:
        with open(path, "a") as f:
            f.write(line)
            f.flush()


def _send_signal(pid: int, sig: signal.Signals) -> bool:
    """Send signal to process group, fall back to single process.

    Returns True if signal was delivered.
    """
    try:
        os.killpg(pid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        pass
    try:
        os.kill(pid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def stop_pipeline(
    issue_id: str,
    project_dir: Path,
    run_dir: Path,
    *,
    timeout: float = 5.0,
    poll_interval: float = 0.2,
) -> bool:
    """Stop a running pipeline. Returns True if process died.

    1. Read PID from lock file
    2. Emit pipeline_stopped event
    3. SIGTERM (killpg, fallback kill)
    4. Poll is_lock_held every poll_interval up to timeout
    5. SIGKILL if still alive
    """
    pid = read_pid_from_lock(issue_id, project_dir)
    if pid is None:
        return False

    _emit_stopped_event(issue_id, run_dir, project_dir)

    if not _send_signal(pid, signal.SIGTERM):
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_lock_held(issue_id, project_dir):
            return True
        time.sleep(poll_interval)

    _send_signal(pid, signal.SIGKILL)

    time.sleep(poll_interval)
    return not is_lock_held(issue_id, project_dir)
