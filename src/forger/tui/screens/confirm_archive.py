"""Confirm archive modal — yes/no before archiving a run."""

from __future__ import annotations

from typing import ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConfirmArchiveModal(ModalScreen[bool]):
    """Confirmation dialog before archiving a run."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "cancel", "No", show=False),
    ]

    DEFAULT_CSS = """
    ConfirmArchiveModal {
        align: center middle;
    }

    #confirm-dialog {
        width: 50;
        height: auto;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
    }

    #confirm-title {
        text-align: center;
        text-style: bold;
        width: 100%;
        padding-bottom: 1;
    }

    #confirm-body {
        width: 100%;
        padding-bottom: 1;
    }

    #confirm-buttons {
        layout: horizontal;
        width: 100%;
        height: auto;
        align-horizontal: right;
    }

    #confirm-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, issue_id: str) -> None:
        super().__init__()
        self._issue_id = issue_id

    def compose(self):
        with Vertical(id="confirm-dialog"):
            yield Label("Archive Run", id="confirm-title")
            yield Label(
                f"Archive [b]{self._issue_id}[/b]?\nThis moves it out of the active list.",
                id="confirm-body",
                markup=True,
            )
            with Grid(id="confirm-buttons"):
                yield Button("No", variant="default", id="btn-no")
                yield Button("Yes", variant="warning", id="btn-yes")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
