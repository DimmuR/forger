"""Stage progress bar widget."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from forger.pipeline import STAGES
from forger.tui.discovery import RunInfo, RunStatus

STAGE_SHORT: dict[str, str] = {
    "sentry_intake": "intake",
    "analyze": "analyze",
    "prove": "prove",
    "fix_options": "fix_opts",
    "implement": "impl",
    "review": "review",
    "draft": "draft",
    "push": "push",
}


class StageProgressBar(Static):
    """Horizontal pipeline stage indicator with color-coded progress."""

    def __init__(self, run: RunInfo, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.run = run

    def update_run(self, run: RunInfo) -> None:
        self.run = run
        self.refresh()

    def render(self) -> Text:
        parts = Text()
        idx = self.run.stage_index
        status = self.run.status

        for i, spec in enumerate(STAGES):
            short = STAGE_SHORT.get(spec.name, spec.name)
            if i > 0:
                parts.append(" → ", style="dim")

            if status == RunStatus.COMPLETED:
                parts.append(f" {short} ", style="bold green")
            elif status in (RunStatus.CRASHED, RunStatus.NEEDS_ATTENTION) and i == idx:
                parts.append(f" {short} ", style="bold white on dark_red")
            elif status == RunStatus.BLOCKED and i == idx:
                parts.append(f" {short} ", style="bold black on yellow")
            elif i < idx:
                parts.append(f" {short} ", style="bold green")
            elif i == idx:
                parts.append(f" {short} ", style="bold white on dark_blue")
            else:
                parts.append(f" {short} ", style="dim")

        return parts
