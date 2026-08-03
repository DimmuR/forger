"""Subprocess spawning and scheduling for pipeline runs from TUI."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from forger.events import format_event_ts


def _find_forger_cmd() -> list[str]:
    """Find the forger CLI executable from the same venv as the running process."""
    venv_bin = Path(sys.executable).parent
    forger_bin = venv_bin / "forger"
    if forger_bin.exists():
        return [str(forger_bin)]
    system_forger = shutil.which("forger")
    if system_forger:
        return [system_forger]
    return [sys.executable, "-m", "forger.cli"]


def spawn_pipeline(
    source: str,
    issue_id: str,
    project_dir: Path,
) -> subprocess.Popen[bytes]:
    """Spawn `forger run <source> <issue_id>` as a detached subprocess.

    Returns Popen handle. The subprocess writes its own lock file;
    TUI discovery picks it up on the next poll cycle.
    """
    from forger.orchestrator import ensure_run_dir

    run_dir = ensure_run_dir(source, issue_id, project_dir)
    stdout_log = run_dir / "stdout.log"

    cmd = [*_find_forger_cmd(), "run", source, issue_id]
    with open(stdout_log, "a") as log_fd:
        proc = subprocess.Popen(
            cmd,
            cwd=str(project_dir),
            stdout=log_fd,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc


def schedule_pipeline(
    source: str,
    issue_id: str,
    project_dir: Path,
    fire_at: datetime,
    params: dict[str, str] | None = None,
) -> Path:
    """Create run dir and write pipeline_scheduled event. Returns run_dir."""
    from forger.orchestrator import ensure_run_dir

    run_dir = ensure_run_dir(source, issue_id, project_dir)
    record = json.dumps(
        {
            "ts": format_event_ts(),
            "type": "pipeline_scheduled",
            "fire_at": fire_at.isoformat(),
            "source": source,
            "issue_id": issue_id,
            "params": params or {},
        },
        separators=(",", ":"),
    )
    with open(run_dir / "events.jsonl", "a") as f:
        f.write(record + "\n")
        f.flush()
    return run_dir


def cancel_schedule(run_dir: Path) -> None:
    """Emit schedule_cancelled event to a run's events.jsonl."""
    record = json.dumps(
        {
            "ts": format_event_ts(),
            "type": "pipeline_schedule_cancelled",
            "reason": "user",
        },
        separators=(",", ":"),
    )
    with open(run_dir / "events.jsonl", "a") as f:
        f.write(record + "\n")
        f.flush()
