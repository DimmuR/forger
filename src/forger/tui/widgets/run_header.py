"""Run header widget — metadata bar for detail screen."""

from __future__ import annotations

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
        if r.parked_reason:
            t.append("  │  ", style="dim")
            t.append(r.parked_reason, style="yellow")
        return t
