"""Run list screen — home screen showing all pipeline runs."""

from __future__ import annotations

from typing import ClassVar

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label
from textual.widgets.data_table import RowKey

from forger.pipeline import STAGES
from forger.tui.discovery import RunInfo, RunStatus, discover_runs

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

STATUS_STYLES: dict[RunStatus, str] = {
    RunStatus.RUNNING: "cyan",
    RunStatus.COMPLETED: "green",
    RunStatus.CRASHED: "red",
    RunStatus.BLOCKED: "yellow",
    RunStatus.NEEDS_ATTENTION: "dark_orange",
}


def _stage_label(stage: str) -> str:
    """Map pipeline state to short display name."""
    for spec in STAGES:
        if spec.post_state == stage:
            return STAGE_SHORT.get(spec.name, spec.name)
        if spec.pre_state == stage:
            return STAGE_SHORT.get(spec.name, spec.name)
    return stage


class RunListScreen(Screen):
    """Home screen: DataTable of all discovered runs."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "select_cursor", "Preview", show=False),
        Binding("e", "open_run", "Preview"),
        Binding("ctrl+q", "quit_app", "Quit"),
        Binding("r", "refresh_runs", "Refresh"),
    ]

    CSS = """
    RunListScreen {
        layout: vertical;
    }

    #title-bar {
        height: 5;
        width: 100%;
        content-align: center middle;
        padding: 1 0;
        border: solid $primary-lighten-2;
        color: $text;
        text-style: bold;
    }

    #run-table {
        height: 1fr;
    }

    #empty-message {
        content-align: center middle;
        height: 1fr;
        color: $text-muted;
    }
    """

    REFRESH_INTERVAL = 3.0

    def __init__(self) -> None:
        super().__init__()
        self._runs: list[RunInfo] = []
        self._row_keys: list[RowKey] = []

    def compose(self):
        yield Header(show_clock=True)
        yield Label(" FORGER — Pipeline Dashboard", id="title-bar")
        yield DataTable(id="run-table", cursor_type="row")
        yield Label(
            "No runs found. Start a pipeline with: forger run sentry <issue-id>",
            id="empty-message",
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#run-table", DataTable)
        table.add_columns(
            "Issue ID",
            "Source",
            "Stage",
            "Status",
            "Title",
        )
        self._load_runs()
        self.set_interval(self.REFRESH_INTERVAL, self._load_runs)

    def _load_runs(self) -> None:
        from pathlib import Path

        project_dir: Path = self.app.project_dir  # type: ignore[attr-defined]
        runs = discover_runs(project_dir)
        self._update_table(runs)

    def _update_table(self, runs: list[RunInfo]) -> None:
        table = self.query_one("#run-table", DataTable)
        empty_msg = self.query_one("#empty-message", Label)

        if not runs:
            table.display = False
            empty_msg.display = True
            self._runs = []
            self._row_keys = []
            return

        table.display = True
        empty_msg.display = False

        old_cursor = table.cursor_row
        table.clear()
        self._row_keys = []
        self._runs = runs

        for run in runs:
            status_text = Text(
                run.status.value.upper(),
                style=STATUS_STYLES.get(run.status, ""),
            )
            stage_text = Text(
                _stage_label(run.stage),
                style="bold" if run.status == RunStatus.RUNNING else "",
            )
            title_truncated = run.title[:60] if len(run.title) > 60 else run.title
            key = table.add_row(
                run.issue_id,
                run.source,
                stage_text,
                status_text,
                title_truncated,
            )
            self._row_keys.append(key)

        if old_cursor is not None and old_cursor < len(runs):
            table.move_cursor(row=old_cursor)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._open_detail(event.cursor_row)

    def action_open_run(self) -> None:
        table = self.query_one("#run-table", DataTable)
        if table.cursor_row is not None and self._runs:
            self._open_detail(table.cursor_row)

    def _open_detail(self, row_index: int) -> None:
        if 0 <= row_index < len(self._runs):
            run = self._runs[row_index]
            self.notify(f"Detail view for {run.issue_id} (coming in #15)")

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_refresh_runs(self) -> None:
        self._load_runs()
        self.notify("Refreshed")
