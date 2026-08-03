"""Subprocess spawning for pipeline runs from TUI."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


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
