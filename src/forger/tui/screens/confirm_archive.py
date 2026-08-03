"""Generic confirmation modal — yes/no before a destructive action."""

from __future__ import annotations

from typing import ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label
from textual.widgets._button import ButtonVariant


class ConfirmModal(ModalScreen[bool]):
    """Parameterized confirmation dialog."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "cancel", "No", show=False),
    ]

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }

    #confirm-dialog {
        width: 50;
        height: auto;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
    }

    #confirm-dialog.--error {
        border: thick $error;
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

    def __init__(
        self,
        title: str,
        body: str,
        *,
        variant: ButtonVariant = "warning",
        error_border: bool = False,
    ) -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._variant: ButtonVariant = variant
        self._error_border = error_border

    def compose(self):
        dialog = Vertical(id="confirm-dialog")
        if self._error_border:
            dialog.add_class("--error")
        with dialog:
            yield Label(self._title, id="confirm-title")
            yield Label(self._body, id="confirm-body", markup=True)
            with Grid(id="confirm-buttons"):
                yield Button("No", variant="default", id="btn-no")
                yield Button("Yes", variant=self._variant, id="btn-yes")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
