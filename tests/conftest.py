"""Shared test fixtures."""

from pathlib import Path

import pytest

from forger.config import BUILTIN_DEFAULTS, ProjectConfig


@pytest.fixture
def config():
    return ProjectConfig.model_validate(BUILTIN_DEFAULTS)


@pytest.fixture
def sentry_intake_dir(tmp_path: Path) -> Path:
    """Create a tmp_path with sentry intake-ui.yml for TUI tests."""
    stages = tmp_path / ".forger" / "stages" / "sentry_intake"
    stages.mkdir(parents=True)
    (stages / "intake-ui.yml").write_text(
        'label: "Sentry"\nparams:\n'
        '  - key: issue_id\n    label: "Issue"\n    type: text\n    required: true\n'
    )
    return tmp_path
