"""Run header widget — metadata bar for detail screen."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rich.text import Text
from textual.widgets import Static

from forger.tui.discovery import RunInfo, RunStatus

STATUS_STYLES: dict[RunStatus, str] = {
    RunStatus.RUNNING: "bold cyan",
    RunStatus.COMPLETED: "bold green",
    RunStatus.CRASHED: "bold red",
    RunStatus.BLOCKED: "bold yellow",
    RunStatus.NEEDS_ATTENTION: "bold dark_orange",
}


def _fmt_elapsed(started: datetime | None, ended: datetime | None) -> str:
    if started is None:
        return ""
    end = ended or datetime.now(UTC)
    total_secs = int((end - started).total_seconds())
    if total_secs < 0:
        return ""
    hours, remainder = divmod(total_secs, 3600)
    mins, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


class RunHeader(Static):
    """Metadata header showing run info."""

    def __init__(self, run: RunInfo, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.run = run

    def update_run(self, run: RunInfo) -> None:
        self.run = run
        self.refresh()

    def render(self) -> Text:
        r = self.run
        t = Text()
        t.append(f"  {r.issue_id}", style="bold")
        t.append("  │  ", style="dim")
        t.append(r.source, style="italic")
        t.append("  │  ", style="dim")
        t.append(r.stage)
        t.append("  │  ", style="dim")
        t.append(r.status.value.upper(), style=STATUS_STYLES.get(r.status, "bold"))
        elapsed = _fmt_elapsed(r.started_at, r.ended_at)
        if elapsed:
            t.append("  │  ", style="dim")
            t.append(elapsed)
        if r.parked_reason:
            t.append("  │  ", style="dim")
            t.append(r.parked_reason, style="yellow")
        return t
