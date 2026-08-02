"""Shared test fixtures."""

import pytest

from forger.config import BUILTIN_DEFAULTS, ProjectConfig


@pytest.fixture
def config():
    return ProjectConfig.model_validate(BUILTIN_DEFAULTS)
