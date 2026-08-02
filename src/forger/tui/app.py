"""Forger TUI dashboard — interactive pipeline observer.

Entry point: `forger-tui` command or `python -m forger.tui.app`.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.app import App
from textual.binding import Binding, BindingType

from forger.tui.screens.run_list import RunListScreen


class ForgerTUI(App):
    """Top-level Textual app for the Forger pipeline dashboard."""

    TITLE = "Forger Dashboard"
    SUB_TITLE = "Pipeline Observability"

    CSS_PATH = "forger.tcss"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, project_dir: Path | None = None) -> None:
        super().__init__()
        self.project_dir = project_dir or Path.cwd()

    def on_mount(self) -> None:
        self.push_screen(RunListScreen())


def run() -> None:
    """Entry point for the `forger-tui` script."""
    app = ForgerTUI()
    app.run()


if __name__ == "__main__":
    run()
