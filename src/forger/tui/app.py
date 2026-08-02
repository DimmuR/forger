"""Forger TUI dashboard — interactive pipeline observer.

Entry point: `forger-tui` command or `python -m forger.tui.app`.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import Footer, Header, Static


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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(
            "No runs found. Start a pipeline with: forger run sentry <issue-id>",
            id="placeholder",
        )
        yield Footer()


def run() -> None:
    """Entry point for the `forger-tui` script."""
    app = ForgerTUI()
    app.run()


if __name__ == "__main__":
    run()
