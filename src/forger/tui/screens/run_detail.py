"""Run detail screen — stage progress and live event stream."""

from __future__ import annotations

import json
from typing import ClassVar

from rich.text import Text
from textual import work
from textual.binding import Binding, BindingType
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog

from forger.tui.discovery import RunInfo, RunStatus
from forger.tui.widgets.run_header import RunHeader
from forger.tui.widgets.stage_bar import StageProgressBar

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

    token_str = f"{tokens / 1000:.1f}k" if tokens >= 1000 else str(tokens)
    t.append(f"{token_str} ", style="green")
    t.append(f"[{name}] ", style="bold")
    t.append("✓", style="green")
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
    elif event_type == "pipeline_end":
        final: str = ev.get("final_stage", "")
        total_tokens: int = ev.get("total_tokens", 0)
        total_elapsed: int = ev.get("total_elapsed_seconds", 0)
        token_str = (
            f"{total_tokens / 1000:.1f}k" if total_tokens >= 1000 else str(total_tokens)
        )
        t.append(f"[{short_ts}] ", style="bold dim")
        t.append(f"Pipeline finished → {final}", style="bold green")
        t.append(f" ({token_str} tokens, {total_elapsed}s)", style="dim")
        blocked: str | None = ev.get("blocked_reason")
        if blocked:
            t.append(f" — {blocked}", style="yellow")
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
    if event_type in ("pipeline_start", "pipeline_end"):
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


class RunDetailScreen(Screen):
    """Detail view for a single pipeline run."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "go_back", "Back", show=False),
        Binding("q", "go_back", "Back"),
        Binding("ctrl+q", "quit_app", "Quit"),
    ]

    CSS = """
    RunDetailScreen {
        layout: vertical;
    }

    #run-header {
        height: 4;
        padding: 1 2;
        background: $surface;
        border-bottom: solid $primary-lighten-2;
    }

    #stage-bar {
        height: 4;
        padding: 1 2;
        background: $surface-darken-1;
        border-bottom: solid $primary-lighten-3;
    }

    #event-log {
        height: 1fr;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    """

    def __init__(self, run: RunInfo) -> None:
        super().__init__()
        self.run = run

    def compose(self):
        yield Header(show_clock=True)
        yield RunHeader(self.run, id="run-header")
        yield StageProgressBar(self.run, id="stage-bar")
        yield RichLog(
            id="event-log", highlight=True, markup=False, wrap=True, max_lines=5000
        )
        yield Footer()

    def on_mount(self) -> None:
        self._load_existing_events()
        if self.run.status == RunStatus.RUNNING:
            self._tail_events()

    def _load_existing_events(self) -> None:
        """Load all existing events from events.jsonl."""
        log = self.query_one("#event-log", RichLog)
        events_path = self.run.run_dir / "events.jsonl"
        if not events_path.exists():
            log.write(Text("No events.jsonl found for this run.", style="dim"))
            return

        self._file_pos = 0
        try:
            with open(events_path) as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        ev = json.loads(stripped)
                        formatted = _format_event(ev)
                        if formatted:
                            log.write(formatted)
                    except json.JSONDecodeError:
                        continue
                self._file_pos = f.tell()
        except OSError:
            log.write(Text("Could not read events.jsonl", style="red"))

    @work(exclusive=True, group="tail")
    async def _tail_events(self) -> None:
        """Poll events.jsonl for new lines while run is active."""
        import asyncio

        log = self.query_one("#event-log", RichLog)
        events_path = self.run.run_dir / "events.jsonl"

        while True:
            await asyncio.sleep(0.5)
            if not events_path.exists():
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
                        formatted = _format_event(ev)
                        if formatted:
                            log.write(formatted)
                        if ev.get("type") == "pipeline_end":
                            return
                    except json.JSONDecodeError:
                        continue
            except OSError:
                continue

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_quit_app(self) -> None:
        self.app.exit()
