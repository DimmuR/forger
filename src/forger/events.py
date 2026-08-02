"""Structured JSONL event emission for pipeline observability.

Writes typed events to events.jsonl in the run directory so that
a TUI or log viewer can tail the file for live progress updates.
"""

__all__ = ["EventEmitter"]

import json
import time
from pathlib import Path
from typing import Any


class EventEmitter:
    """Append-only JSONL writer for pipeline events.

    Each event line contains at minimum ``ts`` (ISO 8601) and ``type``,
    plus any type-specific fields passed as keyword arguments.
    """

    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "events.jsonl"
        self._fh = open(self._path, "a")

    def emit(self, event_type: str, **fields: Any) -> None:
        """Write one JSON event line and flush immediately."""
        record: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
            + f".{int(time.time() * 1000) % 1000:03d}Z",
            "type": event_type,
        }
        record.update(fields)
        self._fh.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._fh.flush()

    def close(self) -> None:
        """Close the underlying file handle."""
        self._fh.close()

    def reattach(self, run_dir: Path) -> None:
        """Close current file and open events.jsonl in a new run_dir.

        Used when the orchestrator relocates run_dir into a worktree.
        """
        self._fh.close()
        self._path = run_dir / "events.jsonl"
        self._fh = open(self._path, "a")
