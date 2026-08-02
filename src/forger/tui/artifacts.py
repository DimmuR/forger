"""Artifact discovery and stage mapping for TUI artifact browser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from forger.pipeline import STAGES

_FILE_TO_STAGE: dict[str, str] = {}
for _spec in STAGES:
    for _artifact in _spec.artifacts:
        _FILE_TO_STAGE[_artifact] = _spec.name

_EXCLUDED = {"events.jsonl", "run.log"}

STAGE_COLORS: dict[str, str] = {
    "sentry_intake": "cyan",
    "analyze": "bright_blue",
    "prove": "magenta",
    "fix_options": "yellow",
    "implement": "green",
    "review": "dark_orange",
    "draft": "bright_cyan",
    "push": "bright_green",
}

STAGE_ORDER: dict[str, int] = {spec.name: i for i, spec in enumerate(STAGES)}


@dataclass(frozen=True)
class ArtifactEntry:
    """One artifact file with its stage and path."""

    name: str
    stage: str
    stage_label: str
    path: Path
    color: str

    @property
    def sort_key(self) -> tuple[int, int, str]:
        if self.stage == "all":
            return (-1, 0, self.name)
        order = STAGE_ORDER.get(self.stage, 999)
        return (order, 0, self.name)


def scan_artifacts(run_dir: Path) -> list[ArtifactEntry]:
    """Scan run directory and return sorted artifact entries."""
    if not run_dir.exists():
        return []

    entries: list[ArtifactEntry] = []

    for child in run_dir.iterdir():
        if child.name.startswith(".") or child.name in _EXCLUDED:
            continue

        if child.is_dir():
            if child.name == "reviews":
                for review_file in sorted(child.iterdir()):
                    if review_file.is_file() and not review_file.name.startswith("."):
                        entries.append(
                            ArtifactEntry(
                                name=f"reviews/{review_file.name}",
                                stage="review",
                                stage_label="review",
                                path=review_file,
                                color=STAGE_COLORS.get("review", "white"),
                            )
                        )
            continue

        if child.name == "change.md":
            entries.append(
                ArtifactEntry(
                    name=child.name,
                    stage="all",
                    stage_label="all",
                    path=child,
                    color="white",
                )
            )
            continue

        stage = _FILE_TO_STAGE.get(child.name)
        if stage is None:
            continue

        from forger.tui.constants import STAGE_SHORT

        entries.append(
            ArtifactEntry(
                name=child.name,
                stage=stage,
                stage_label=STAGE_SHORT.get(stage, stage),
                path=child,
                color=STAGE_COLORS.get(stage, "white"),
            )
        )

    entries.sort(key=lambda e: e.sort_key)
    return entries
