"""Run header widget — metadata bar for detail screen."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from forger.tui.constants import STATUS_STYLES, format_elapsed, stage_label
from forger.tui.discovery import RunInfo


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
        sep = ("  │  ", "dim")
        t = Text()
        t.append(r.issue_id, style="bold")
        t.append(*sep)
        t.append(r.source, style="italic")
        t.append(*sep)
        t.append(stage_label(r.stage))
        t.append(*sep)
        t.append(r.status.value.upper(), style=STATUS_STYLES.get(r.status, "bold"))
        elapsed = format_elapsed(r.started_at, r.ended_at)
        if elapsed and elapsed != "—":
            t.append(*sep)
            t.append(elapsed)
        if r.parked_reason:
            t.append(*sep)
            t.append(r.parked_reason, style="yellow")
        if r.title:
            t.append(*sep)
            title = r.title[:40] + "..." if len(r.title) > 40 else r.title
            t.append(title, style="dim italic")
        return t
