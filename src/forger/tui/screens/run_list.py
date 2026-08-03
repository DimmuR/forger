"""Run list screen — home screen showing all pipeline runs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Label
from textual.widgets.data_table import RowKey

from forger.tui.constants import (
    STATUS_STYLES,
    format_elapsed,
    format_started,
    stage_label,
)
from forger.tui.discovery import RunInfo, RunStatus, discover_runs
from forger.tui.stopper import stop_pipeline


class RunListScreen(Screen):
    """Home screen: DataTable of all discovered runs."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "select_cursor", "Open", show=False),
        Binding("e", "open_run", "Open"),
        Binding("n", "new_intake", "New"),
        Binding("s", "stop_run", "Stop"),
        Binding("d", "archive_run", "Archive"),
        Binding("r", "refresh_runs", "Refresh"),
        Binding("ctrl+q", "quit_app", "Quit"),
    ]

    REFRESH_INTERVAL = 3.0

    def __init__(self) -> None:
        super().__init__()
        self._runs: list[RunInfo] = []
        self._row_keys: list[RowKey] = []

    def compose(self):
        yield Header(show_clock=True)
        yield Label("FORGER — Pipeline Dashboard", id="title-bar")
        yield DataTable(id="run-table", cursor_type="row")
        yield Label(
            "No runs found. Start a pipeline with: forger run sentry <issue-id>",
            id="empty-message",
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#run-table", DataTable)
        table.add_column("Issue ID", width=30)
        table.add_column("Source", width=10)
        table.add_column("Stage", width=12)
        table.add_column("Status", width=18)
        table.add_column("Started", width=12)
        table.add_column("Elapsed", width=10)
        table.add_column("Title")
        self._load_runs()
        self.set_interval(self.REFRESH_INTERVAL, self._load_runs)

    def _load_runs(self) -> None:
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
                stage_label(run.stage),
                style="bold" if run.status == RunStatus.RUNNING else "",
            )
            started = format_started(run.started_at)
            elapsed = format_elapsed(run.started_at, run.ended_at)
            title_truncated = (
                run.title[:57] + "..." if len(run.title) > 60 else run.title
            )
            key = table.add_row(
                run.issue_id,
                run.source,
                stage_text,
                status_text,
                started,
                elapsed,
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
            from forger.tui.screens.run_detail import RunDetailScreen

            run = self._runs[row_index]
            self.app.push_screen(RunDetailScreen(run))

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_refresh_runs(self) -> None:
        self._load_runs()
        self.notify("Refreshed")

    def _selected_run(self) -> tuple[int, RunInfo] | None:
        table = self.query_one("#run-table", DataTable)
        if table.cursor_row is None or not self._runs:
            return None
        idx = table.cursor_row
        if idx < 0 or idx >= len(self._runs):
            return None
        return idx, self._runs[idx]

    def action_archive_run(self) -> None:
        from forger.tui.screens.confirm_archive import ConfirmModal

        sel = self._selected_run()
        if not sel:
            return
        _idx, run = sel

        if run.status in (RunStatus.RUNNING, RunStatus.STOPPING):
            self.notify("Cannot archive a running job", severity="warning")
            return

        def on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            source_dir = run.run_dir.parent
            archive_dir = source_dir / "archive"
            archive_dir.mkdir(exist_ok=True)
            dest = archive_dir / run.run_dir.name
            try:
                run.run_dir.rename(dest)
            except OSError as exc:
                self.notify(f"Archive failed: {exc}", severity="error")
                return
            self.notify(f"Archived {run.issue_id}")
            self._load_runs()

        self.app.push_screen(
            ConfirmModal(
                "Archive Run",
                f"Archive [b]{run.issue_id}[/b]?\nThis moves it out of the active list.",
            ),
            on_confirm,
        )

    def action_stop_run(self) -> None:
        from forger.tui.screens.confirm_archive import ConfirmModal

        sel = self._selected_run()
        if not sel:
            return
        idx, run = sel

        if run.status != RunStatus.RUNNING:
            self.notify("Can only stop a running job", severity="warning")
            return

        def on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._runs[idx] = replace(run, status=RunStatus.STOPPING)
            self._update_table(self._runs)
            self._do_stop(run)

        self.app.push_screen(
            ConfirmModal(
                "Stop Pipeline",
                f"Stop working on [b]{run.issue_id}[/b]?",
                variant="error",
                error_border=True,
            ),
            on_confirm,
        )

    @work(thread=True)
    def _do_stop(self, run: RunInfo) -> None:
        project_dir: Path = self.app.project_dir  # type: ignore[attr-defined]
        killed = stop_pipeline(run.issue_id, project_dir, run.run_dir)
        if killed:
            self.app.call_from_thread(self.notify, f"Stopped {run.issue_id}")
        else:
            self.app.call_from_thread(
                self.notify, f"Failed to stop {run.issue_id}", severity="error"
            )
        self.app.call_from_thread(self._load_runs)

    def action_new_intake(self) -> None:
        from forger.tui.intakes import discover_intakes
        from forger.tui.screens.new_intake import IntakeRequest, NewIntakeModal

        project_dir: Path = self.app.project_dir  # type: ignore[attr-defined]
        intakes = discover_intakes(project_dir)
        if not intakes:
            self.notify("No intakes found", severity="warning")
            return

        def on_result(result: IntakeRequest | None) -> None:
            if result is None:
                return
            from forger.tui.spawner import spawn_pipeline

            issue_id = result.params.get("issue_id", "")
            if not issue_id:
                self.notify("No issue ID provided", severity="error")
                return
            try:
                spawn_pipeline(result.source, issue_id, project_dir)
            except OSError as exc:
                self.notify(f"Spawn failed: {exc}", severity="error")
                return
            self.notify(f"Started {result.source} intake: {issue_id}")
            self._load_runs()

        self.app.push_screen(NewIntakeModal(intakes), on_result)
