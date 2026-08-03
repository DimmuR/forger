"""Run detail screen — stage progress and live event stream."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, RichLog

from forger import worktree
from forger.pipeline import STAGE_BY_NAME
from forger.tui.constants import format_tokens
from forger.tui.discovery import RunInfo, RunStatus, _parse_ts, discover_runs
from forger.tui.widgets.artifact_browser import ArtifactBrowser
from forger.tui.widgets.run_header import RunHeader
from forger.tui.widgets.stage_bar import StageProgressBar

_ACTIVE_STATUSES = (RunStatus.RUNNING, RunStatus.BLOCKED)

TOOL_ICONS: dict[str, tuple[str, str]] = {
    "Read": ("[R]", "bold cyan"),
    "Write": ("[W]", "bold magenta"),
    "Edit": ("[E]", "bold magenta"),
    "Bash": ("[B]", "bold yellow"),
    "WebSearch": ("[S]", "bold blue"),
    "WebFetch": ("[F]", "bold blue"),
}


def _format_tool_event(ev: dict) -> Text:
    """Format a tool_use event line."""
    t = Text()
    t.append("       ", style="dim")
    name: str = ev.get("name", "")
    summary: str = ev.get("input_summary", name)
    icon, style = TOOL_ICONS.get(name, ("[T]", "bold"))
    t.append(f"{icon} ", style=style)
    t.append(summary)
    return t


def _format_stage_start(ev: dict) -> Text:
    t = Text()
    ts: str = ev.get("ts", "")
    short_ts = ts[11:19] if len(ts) >= 19 else ts
    name: str = ev.get("name", "?")
    model: str = ev.get("model", "")
    t.append(f"[{short_ts}] ", style="bold dim")
    t.append(f"[{name}]", style="bold")
    t.append(" started", style="")
    if model:
        t.append(f" (model={model})", style="dim")
    return t


def _format_stage_end(ev: dict) -> Text:
    t = Text()
    ts: str = ev.get("ts", "")
    short_ts = ts[11:19] if len(ts) >= 19 else ts
    name: str = ev.get("name", "?")
    tokens: int = ev.get("tokens", 0)
    elapsed: int = ev.get("elapsed_seconds", 0)
    new_stage: str = ev.get("new_stage", "")

    t.append(f"[{short_ts}] ", style="bold dim")

    success: bool = ev.get("success", True)
    token_str = format_tokens(tokens)
    t.append(f"{token_str} ", style="green" if success else "red")
    t.append(f"[{name}] ", style="bold")
    if success:
        t.append("✓", style="green")
    else:
        t.append("✗", style="red")
        error: str = ev.get("error") or ""
        if error:
            t.append(f" {error}", style="red")
    if new_stage:
        t.append(f" → {new_stage}", style="")
    t.append(f" (+{elapsed}s / +{token_str})", style="dim")
    return t


def _format_blocked(ev: dict) -> Text:
    t = Text()
    reason: str = ev.get("reason", "unknown")
    t.append("  ⚠ ", style="yellow")
    t.append(reason, style="yellow")
    return t


def _format_pipeline_event(ev: dict) -> Text:
    t = Text()
    ts: str = ev.get("ts", "")
    short_ts = ts[11:19] if len(ts) >= 19 else ts
    event_type: str = ev.get("type", "")

    if event_type == "pipeline_start":
        source: str = ev.get("source", "")
        issue: str = ev.get("issue_id", "")
        t.append(f"[{short_ts}] ", style="bold dim")
        t.append(f"Pipeline started: {source}/{issue}", style="bold cyan")
    elif event_type == "pipeline_stopped":
        t.append(f"[{short_ts}] ", style="bold dim")
        t.append("Pipeline stopped by user", style="bold dark_orange")
    elif event_type == "pipeline_end":
        final: str = ev.get("final_stage", "")
        total_tokens: int = ev.get("total_tokens", 0)
        total_elapsed: int = ev.get("total_elapsed_seconds", 0)
        token_str = format_tokens(total_tokens)
        t.append(f"[{short_ts}] ", style="bold dim")
        blocked: str | None = ev.get("blocked_reason")
        if blocked:
            t.append(f"Pipeline failed → {final}", style="bold red")
            t.append(f" ({token_str} tokens, {total_elapsed}s)", style="dim")
            t.append(f" — {blocked}", style="yellow")
        else:
            t.append(f"Pipeline finished → {final}", style="bold green")
            t.append(f" ({token_str} tokens, {total_elapsed}s)", style="dim")
    return t


def _format_event(ev: dict) -> Text | None:
    """Route event to formatter by type."""
    event_type: str = ev.get("type", "")
    if event_type == "tool_use":
        return _format_tool_event(ev)
    if event_type == "stage_start":
        return _format_stage_start(ev)
    if event_type == "stage_end":
        return _format_stage_end(ev)
    if event_type == "blocked":
        return _format_blocked(ev)
    if event_type in ("pipeline_start", "pipeline_end", "pipeline_stopped"):
        return _format_pipeline_event(ev)
    if event_type == "skip":
        t = Text()
        t.append(f"  [{ev.get('name', '?')}] ", style="dim")
        t.append("skipped", style="dim")
        return t
    if event_type == "heartbeat":
        return None
    if event_type == "worktree":
        t = Text()
        action: str = ev.get("action", "")
        path: str = ev.get("path", "")
        t.append(f"  worktree {action}: ", style="dim")
        t.append(path, style="dim")
        return t
    return None


def _find_events_paths(run: RunInfo, project_dir: Path) -> list[Path]:
    """Return all events.jsonl paths for a run, including worktree.

    Canonical path first, then worktree path if it exists.
    """
    paths: list[Path] = []
    canonical = run.run_dir / "events.jsonl"
    if canonical.exists():
        paths.append(canonical)

    wt_path = worktree.path_for(run.issue_id, project_dir)
    if wt_path:
        wt_events = worktree.worktree_run_dir(wt_path) / "events.jsonl"
        if wt_events.exists() and wt_events != canonical:
            paths.append(wt_events)

    return paths


class RunDetailScreen(Screen):
    """Detail view for a single pipeline run."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "go_back", "Back", show=False),
        Binding("q", "go_back", "Back"),
        Binding("a", "toggle_artifacts", "Artifacts"),
        Binding("ctrl+q", "quit_app", "Quit"),
    ]

    REFRESH_INTERVAL = 3.0

    def __init__(self, run: RunInfo) -> None:
        super().__init__()
        self.run = run
        self._file_pos: int = 0
        self._current_events_path: Path | None = None
        self._live_stage: str | None = None
        self._stage_times: dict[str, int] = {}
        self._stage_start_ts: dict[str, str] = {}
        self._run_gone: bool = False

    @property
    def _project_dir(self) -> Path:
        return self.app.project_dir  # type: ignore[attr-defined, return-value, no-any-return]

    def compose(self):
        yield Header(show_clock=True)
        yield RunHeader(self.run, id="run-header")
        yield StageProgressBar(self.run, id="stage-bar")
        with Horizontal(id="main-content"):
            yield RichLog(
                id="event-log",
                highlight=True,
                markup=False,
                wrap=True,
                max_lines=5000,
            )
            yield ArtifactBrowser(
                self.run.run_dir, id="artifact-browser", classes="-hidden"
            )
        yield Label(
            "Run directory no longer exists. Press q to go back.",
            id="run-gone",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#run-gone").display = False
        self._load_existing_events()
        if self.run.status in _ACTIVE_STATUSES:
            self._tail_events()
            self.set_interval(self.REFRESH_INTERVAL, self._refresh_run_info)

    def _refresh_run_info(self) -> None:
        """Re-read run state and update header + stage bar."""
        if not self.run.run_dir.exists():
            self._show_run_gone()
            return
        project_dir: Path = self.app.project_dir  # type: ignore[attr-defined]
        runs = discover_runs(project_dir)
        for r in runs:
            if r.issue_id == self.run.issue_id and r.source == self.run.source:
                self.run = r
                break
        else:
            self._show_run_gone()
            return
        self._update_widgets()
        browser = self.query_one("#artifact-browser", ArtifactBrowser)
        if not browser.has_class("-hidden"):
            browser.refresh_artifacts()

    def _show_run_gone(self) -> None:
        if self._run_gone:
            return
        self._run_gone = True
        self.query_one("#run-header").display = False
        self.query_one("#stage-bar").display = False
        self.query_one("#event-log").display = False
        self.query_one("#run-gone").display = True
        self.notify("Run directory was removed", severity="warning")

    def _track_event(self, ev: dict) -> None:
        """Track stage transitions and timings from events."""
        event_type: str = ev.get("type", "")
        if event_type == "pipeline_start":
            self._stage_times.clear()
            self._stage_start_ts.clear()
            self._live_stage = None
        elif event_type == "stage_start":
            name: str = ev.get("name", "")
            self._live_stage = name
            self._stage_start_ts[name] = ev.get("ts", "")
            self._stage_times.pop(name, None)
        elif event_type == "stage_end":
            name = ev.get("name", "")
            elapsed: int = ev.get("elapsed_seconds", 0)
            if elapsed:
                self._stage_times[name] = elapsed
            spec = STAGE_BY_NAME.get(name)
            if spec:
                self._live_stage = spec.post_state

    def _update_widgets(self) -> None:
        """Update header and stage bar, preferring live stage over change.md."""
        run = self.run
        if self._live_stage and self._live_stage != run.stage:
            run = replace(run, stage=self._live_stage)
        self.query_one("#run-header", RunHeader).update_run(run)

        times = dict(self._stage_times)
        if self._live_stage and self._live_stage not in times:
            ts_raw = self._stage_start_ts.get(self._live_stage, "")
            if ts_raw:
                started = _parse_ts(ts_raw)
                if started:
                    elapsed = int((datetime.now(UTC) - started).total_seconds())
                    if elapsed >= 0:
                        times[self._live_stage] = elapsed

        bar = self.query_one("#stage-bar", StageProgressBar)
        bar.update_run(run)
        bar.update_times(times)

    def _load_existing_events(self) -> None:
        """Load all existing events from events.jsonl files."""
        log = self.query_one("#event-log", RichLog)
        paths = _find_events_paths(self.run, self._project_dir)

        if not paths:
            log.write(Text("No events.jsonl found for this run.", style="dim"))
            return

        for events_path in paths:
            try:
                with open(events_path) as f:
                    for line in f:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        try:
                            ev = json.loads(stripped)
                            self._track_event(ev)
                            formatted = _format_event(ev)
                            if formatted:
                                log.write(formatted)
                        except json.JSONDecodeError:
                            continue
                    self._file_pos = f.tell()
                    self._current_events_path = events_path
            except OSError:
                continue
        self._update_widgets()

    @work(exclusive=True, group="tail")
    async def _tail_events(self) -> None:
        """Poll events.jsonl for new lines while run is active."""
        import asyncio

        log = self.query_one("#event-log", RichLog)

        while not self._run_gone:
            await asyncio.sleep(0.5)

            if not self.run.run_dir.exists():
                self._show_run_gone()
                return

            # Check for worktree events.jsonl appearing
            paths = _find_events_paths(self.run, self._project_dir)
            if paths:
                latest_path = paths[-1]
                if (
                    self._current_events_path is not None
                    and latest_path != self._current_events_path
                ):
                    # Switched to worktree — read from start of new file
                    self._current_events_path = latest_path
                    self._file_pos = 0

            events_path = self._current_events_path
            if events_path is None or not events_path.exists():
                # No events file yet — check if canonical appeared
                canonical = self.run.run_dir / "events.jsonl"
                if canonical.exists():
                    self._current_events_path = canonical
                    self._file_pos = 0
                    events_path = canonical
                else:
                    continue

            try:
                with open(events_path) as f:
                    f.seek(self._file_pos)
                    new_lines = f.readlines()
                    self._file_pos = f.tell()
                for line in new_lines:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        ev = json.loads(stripped)
                        self._track_event(ev)
                        formatted = _format_event(ev)
                        if formatted:
                            log.write(formatted)
                        if ev.get("type") in ("stage_start", "stage_end"):
                            self._update_widgets()
                        if ev.get("type") == "pipeline_end":
                            self._refresh_run_info()
                            return
                    except json.JSONDecodeError:
                        continue
            except OSError:
                continue

    def action_toggle_artifacts(self) -> None:
        browser = self.query_one("#artifact-browser", ArtifactBrowser)
        browser.toggle_class("-hidden")
        if browser.has_class("-hidden"):
            self.set_focus(self.query_one("#event-log"))
        else:
            browser.refresh_artifacts()
            self.set_focus(self.query_one("#artifact-list"))

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.exit()
