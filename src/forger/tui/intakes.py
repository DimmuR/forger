"""Intake discovery and config loading for TUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class IntakeParam:
    key: str
    label: str
    type: str = "text"
    placeholder: str = ""
    required: bool = False
    options: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class IntakeConfig:
    source: str
    label: str
    params: list[IntakeParam]


def _load_intake_ui(source: str, path: Path) -> IntakeConfig | None:
    ui_path = path / "intake-ui.yml"
    if not ui_path.exists():
        return None
    try:
        with open(ui_path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        params = [IntakeParam(**p) for p in data.get("params", [])]
    except (TypeError, KeyError):
        return None
    return IntakeConfig(
        source=source,
        label=data.get("label", source.title()),
        params=params,
    )


def discover_intakes(project_dir: Path | None = None) -> list[IntakeConfig]:
    """Scan *_intake/ dirs in package + project stages for intake-ui.yml."""
    intakes: dict[str, IntakeConfig] = {}

    pkg_stages = Path(__file__).parent.parent / "stages"
    for d in sorted(pkg_stages.iterdir()):
        if d.is_dir() and d.name.endswith("_intake"):
            source = d.name.removesuffix("_intake")
            cfg = _load_intake_ui(source, d)
            if cfg:
                intakes[source] = cfg

    if project_dir:
        project_stages = project_dir / ".forger" / "stages"
        if project_stages.exists():
            for d in sorted(project_stages.iterdir()):
                if d.is_dir() and d.name.endswith("_intake"):
                    source = d.name.removesuffix("_intake")
                    cfg = _load_intake_ui(source, d)
                    if cfg:
                        intakes[source] = cfg

    return list(intakes.values())
