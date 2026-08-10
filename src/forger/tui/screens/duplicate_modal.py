"""Duplicate detection modal — shown when intake finds an existing run."""

from __future__ import annotations

from typing import ClassVar, Literal

from textual.binding import Binding, BindingType
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label

from forger.tui.constants import stage_label
from forger.tui.discovery import RunInfo, RunStatus

DupeAction = Literal["cancel", "view", "restart", "unarchive"]

_RESTARTABLE = frozenset(
    {
        RunStatus.STOPPED,
        RunStatus.CRASHED,
        RunStatus.FAILED,
        RunStatus.NEEDS_ATTENTION,
        RunStatus.BLOCKED,
    }
)


class DuplicateModal(ModalScreen[DupeAction]):
    """Shows existing run info and offers context-dependent actions."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    DEFAULT_CSS = """
    DuplicateModal {
        align: center middle;
    }

    #dupe-dialog {
        width: 60;
        height: auto;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
    }

    #dupe-title {
        text-align: center;
        text-style: bold;
        width: 100%;
        padding-bottom: 1;
    }

    #dupe-info {
        width: 100%;
        padding-bottom: 1;
    }

    #dupe-buttons {
        layout: horizontal;
        width: 100%;
        height: auto;
        align-horizontal: right;
    }

    #dupe-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, run: RunInfo) -> None:
        super().__init__()
        self._run = run

    def compose(self):
        r = self._run
        with Vertical(id="dupe-dialog"):
            yield Label("Duplicate Found", id="dupe-title")

            lines = [
                f"[b]{r.issue_id}[/b] already exists.",
                f"Status: [b]{r.status.value.upper()}[/b]  Stage: [b]{stage_label(r.stage)}[/b]",
            ]
            if r.title and r.title != r.issue_id:
                lines.append(f"Title: {r.title}")
            if r.parked_reason:
                lines.append(f"Reason: {r.parked_reason}")
            if r.is_archived:
                lines.append("[dim]This item is archived.[/dim]")

            yield Label("\n".join(lines), id="dupe-info", markup=True)

            with Grid(id="dupe-buttons"):
                yield Button("Cancel", variant="default", id="btn-cancel")
                yield Button("View Details", variant="primary", id="btn-view")
                if r.is_archived:
                    yield Button("Unarchive", variant="warning", id="btn-unarchive")
                elif r.status in _RESTARTABLE:
                    yield Button("Restart", variant="warning", id="btn-restart")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "btn-view":
                self.dismiss("view")
            case "btn-restart":
                self.dismiss("restart")
            case "btn-unarchive":
                self.dismiss("unarchive")
            case _:
                self.dismiss("cancel")

    def action_cancel(self) -> None:
        self.dismiss("cancel")
