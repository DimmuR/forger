"""Stage progress bar widget."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from forger.pipeline import STAGES
from forger.tui.constants import STAGE_SHORT, format_seconds
from forger.tui.discovery import RunInfo, RunStatus


class StageProgressBar(Static):
    """Horizontal pipeline stage indicator with color-coded progress."""

    def __init__(self, run: RunInfo, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.run = run
        self.stage_times: dict[str, int] = {}

    def update_run(self, run: RunInfo) -> None:
        self.run = run
        self.refresh()

    def update_times(self, stage_times: dict[str, int]) -> None:
        self.stage_times = stage_times
        self.refresh()

    def render(self) -> Text:
        parts = Text()
        idx = self.run.stage_index
        status = self.run.status

        for i, spec in enumerate(STAGES):
            short = STAGE_SHORT.get(spec.name, spec.name)
            elapsed = self.stage_times.get(spec.name)
            label = f" {short} "
            if elapsed is not None:
                label = f" {short} ({format_seconds(elapsed)}) "

            if i > 0:
                parts.append(" → ", style="dim")

            if status == RunStatus.COMPLETED:
                parts.append(label, style="bold green")
            elif status in (RunStatus.CRASHED, RunStatus.NEEDS_ATTENTION) and i == idx:
                parts.append(label, style="bold white on dark_red")
            elif status == RunStatus.BLOCKED and i == idx:
                parts.append(label, style="bold black on yellow")
            elif i < idx:
                parts.append(label, style="bold green")
            elif i == idx:
                parts.append(label, style="bold white on dark_blue")
            else:
                parts.append(label, style="dim")

        return parts
