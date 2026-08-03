"""New intake modal — dynamic form built from intake-ui.yml config."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

from textual.binding import Binding, BindingType
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Switch

from forger.tui.intakes import IntakeConfig, IntakeParam


def _parse_schedule(raw: str) -> datetime | None:
    """Parse schedule string. Accepts 'HH:MM' (next occurrence) or 'YYYY-MM-DD HH:MM'."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    local_tz = ZoneInfo("localtime")

    for fmt in ("%Y-%m-%d %H:%M", "%H:%M"):
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue

        if fmt == "%H:%M":
            now = datetime.now(local_tz)
            candidate = now.replace(
                hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0
            )
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate.astimezone(UTC)

        fire_at = parsed.replace(tzinfo=local_tz).astimezone(UTC)
        if fire_at <= datetime.now(UTC):
            return None
        return fire_at

    return None


@dataclass
class IntakeRequest:
    source: str
    params: dict[str, str]
    fire_at: datetime | None = None


class NewIntakeModal(ModalScreen[IntakeRequest | None]):
    """Modal form for starting a new intake run."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "submit", "Submit", show=False),
    ]

    DEFAULT_CSS = """
    NewIntakeModal {
        align: center middle;
    }

    #intake-dialog {
        width: 60;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #intake-title {
        text-align: center;
        text-style: bold;
        width: 100%;
        padding-bottom: 1;
    }

    #source-select {
        width: 100%;
        margin-bottom: 1;
    }

    #param-container {
        width: 100%;
        height: auto;
        max-height: 60%;
        overflow-y: auto;
    }

    .param-label {
        padding: 0 0 0 0;
        color: $text-muted;
    }

    .param-input {
        width: 100%;
        margin-bottom: 1;
    }

    .schedule-label {
        padding: 0;
        color: $text-muted;
    }

    #schedule-input {
        width: 100%;
        margin-bottom: 1;
    }

    #button-bar {
        layout: horizontal;
        width: 100%;
        height: auto;
        padding-top: 1;
        align-horizontal: right;
    }

    #button-bar Button {
        margin-left: 1;
    }
    """

    def __init__(self, intakes: list[IntakeConfig]) -> None:
        super().__init__()
        self._intakes = intakes
        self._intake_map = {cfg.source: cfg for cfg in intakes}
        self._current: IntakeConfig | None = intakes[0] if intakes else None

    def compose(self):
        with Vertical(id="intake-dialog"):
            yield Label("New Intake", id="intake-title")

            options = [(cfg.label, cfg.source) for cfg in self._intakes]
            yield Select(
                options,
                prompt="Select source",
                allow_blank=False,
                value=self._intakes[0].source if self._intakes else Select.BLANK,
                id="source-select",
            )

            yield Vertical(id="param-container")

            yield Label("Schedule (leave empty for now)", classes="schedule-label")
            yield Input(
                placeholder="HH:MM or YYYY-MM-DD HH:MM",
                id="schedule-input",
            )

            with Grid(id="button-bar"):
                yield Button("Cancel", variant="default", id="btn-cancel")
                yield Button("Start", variant="primary", id="btn-start")

    def on_mount(self) -> None:
        if self._current:
            self._mount_params(self._current)

    async def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "source-select" or event.value == Select.BLANK:
            return
        new_source = str(event.value)
        if self._current and self._current.source == new_source:
            return
        self._current = self._intake_map.get(new_source)
        if self._current:
            container = self.query_one("#param-container", Vertical)
            await container.remove_children()
            self._mount_params(self._current)

    def _mount_params(self, cfg: IntakeConfig) -> None:
        container = self.query_one("#param-container", Vertical)
        widgets = []
        for param in cfg.params:
            widgets.extend(self._make_param_widgets(param))
        container.mount_all(widgets)

    def _make_param_widgets(
        self, param: IntakeParam
    ) -> list[Label | Input | Select | Switch]:
        suffix = " *" if param.required else ""
        label = Label(f"{param.label}{suffix}", classes="param-label")

        if param.type == "select":
            options = [(opt, opt) for opt in param.options]
            widget: Input | Select | Switch = Select(
                options,
                prompt=param.placeholder or f"Select {param.label}",
                allow_blank=not param.required,
                id=f"param-{param.key}",
                classes="param-input",
            )
        elif param.type == "bool":
            widget = Switch(value=False, id=f"param-{param.key}")
        else:
            widget = Input(
                placeholder=param.placeholder,
                id=f"param-{param.key}",
                classes="param-input",
            )

        return [label, widget]

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-start":
            self._submit()

    def _submit(self) -> None:
        if not self._current:
            return

        params: dict[str, str] = {}
        for param in self._current.params:
            widget_id = f"param-{param.key}"
            try:
                widget = self.query_one(f"#{widget_id}")
            except Exception:
                continue

            if isinstance(widget, Input):
                value = widget.value.strip()
            elif isinstance(widget, Select):
                value = str(widget.value) if widget.value != Select.BLANK else ""
            elif isinstance(widget, Switch):
                value = str(widget.value)
            else:
                value = ""

            if param.required and not value:
                self.notify(f"{param.label} is required", severity="error")
                return

            params[param.key] = value

        fire_at: datetime | None = None
        schedule_raw = self.query_one("#schedule-input", Input).value.strip()
        if schedule_raw:
            fire_at = _parse_schedule(schedule_raw)
            if fire_at is None:
                self.notify(
                    "Invalid format. Use HH:MM or YYYY-MM-DD HH:MM", severity="error"
                )
                return

        self.dismiss(
            IntakeRequest(source=self._current.source, params=params, fire_at=fire_at)
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self._submit()
