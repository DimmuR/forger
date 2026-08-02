"""Artifact browser widget — file list + preview panel."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from rich.text import Text
from textual import on
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widgets import Markdown, OptionList, Static
from textual.widgets.option_list import Option

from forger.tui.artifacts import ArtifactEntry, scan_artifacts


class ArtifactBrowser(Vertical):
    """Togglable sidebar with artifact file list and markdown preview."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("c", "copy_path", "Copy path", show=False),
        Binding("y", "copy_path", "Copy path", show=False),
    ]

    def __init__(self, run_dir: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.run_dir = run_dir
        self._entries: list[ArtifactEntry] = []
        self._selected_path: Path | None = None

    def compose(self):
        yield OptionList(id="artifact-list")
        yield Markdown(id="artifact-preview")
        yield Static("Select a file to preview", id="artifact-empty")

    def on_mount(self) -> None:
        self.query_one("#artifact-preview").display = False
        self.refresh_artifacts()

    def refresh_artifacts(self) -> None:
        """Re-scan run directory and update file list."""
        new_entries = scan_artifacts(self.run_dir)
        if [e.name for e in new_entries] == [e.name for e in self._entries]:
            return
        self._entries = new_entries
        option_list = self.query_one("#artifact-list", OptionList)
        option_list.clear_options()
        for entry in self._entries:
            label = Text()
            tag = f"[{entry.stage_label}]"
            label.append(f"{tag:>12} ", style=f"bold {entry.color}")
            label.append(entry.name)
            option_list.add_option(Option(label, id=entry.name))

    @on(OptionList.OptionSelected, "#artifact-list")
    async def _on_file_selected(self, event: OptionList.OptionSelected) -> None:
        """Load and preview selected artifact."""
        option_id = event.option_id
        if option_id is None:
            return
        entry = next((e for e in self._entries if e.name == option_id), None)
        if entry is None:
            return

        self._selected_path = entry.path
        try:
            content = entry.path.read_text(errors="replace")
        except OSError:
            content = f"*Error reading {entry.path}*"

        preview = self.query_one("#artifact-preview", Markdown)
        empty = self.query_one("#artifact-empty")

        if entry.name.endswith(".md"):
            await preview.update(content)
        else:
            await preview.update(f"```\n{content}\n```")

        preview.display = True
        empty.display = False

    def action_copy_path(self) -> None:
        """Copy selected file path to clipboard."""
        if self._selected_path is None:
            option_list = self.query_one("#artifact-list", OptionList)
            idx = option_list.highlighted
            if idx is not None and idx < len(self._entries):
                self._selected_path = self._entries[idx].path

        if self._selected_path is None:
            self.notify("No file selected", severity="warning")
            return

        path_str = str(self._selected_path)
        self.app.copy_to_clipboard(path_str)
        self.notify(f"Copied: {path_str}", timeout=3)
