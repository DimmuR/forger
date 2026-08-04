import pytest
from pydantic import ValidationError

from forger.config import (
    BUILTIN_DEFAULTS,
    PipelineConfig,
    ProjectConfig,
    _deep_merge,
    load_config,
)


def test_builtin_defaults():
    config = ProjectConfig.model_validate(BUILTIN_DEFAULTS)
    assert config.models.default == "sonnet"
    assert config.models.stages["review"] == "opus"
    assert config.models.stages["sentry_intake"] == "opus"
    assert config.default_runner == "claude"
    assert "claude" in config.runners
    assert config.runners["claude"].timeout == 900
    assert config.timeout.default == 900
    assert "sentry" in config.pipelines
    assert config.pipelines["sentry"].stages[0] == "sentry_intake"
    assert config.pipelines["sentry"].stages[-1] == "create_pr"


def test_deep_merge():
    base = {"a": 1, "b": {"c": 2, "d": 3}, "e": [1, 2]}
    override = {"b": {"c": 99, "f": 4}, "g": 5}
    result = _deep_merge(base, override)
    assert result == {"a": 1, "b": {"c": 99, "d": 3, "f": 4}, "e": [1, 2], "g": 5}


def test_load_config_no_files(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "forger.config.GLOBAL_CONFIG_PATH", tmp_path / "nonexistent.yaml"
    )
    config = load_config(project_dir=tmp_path)
    assert config.models.default == "sonnet"
    assert config.default_runner == "claude"


def test_load_config_project_override(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "forger.config.GLOBAL_CONFIG_PATH", tmp_path / "nonexistent.yaml"
    )
    project_config_dir = tmp_path / ".forger"
    project_config_dir.mkdir()
    (project_config_dir / "config.yaml").write_text("""
models:
  default: opus
  stages:
    implement: opus
commands:
  test: "pytest backend/"
  lint: "ruff check ."
base_branch: develop
""")
    config = load_config(project_dir=tmp_path)
    assert config.models.default == "opus"
    assert config.models.stages["implement"] == "opus"
    assert config.models.stages["review"] == "opus"  # inherited from builtin
    assert config.commands["test"] == "pytest backend/"
    assert config.base_branch == "develop"


def test_load_config_global_and_project(tmp_path, monkeypatch):
    global_path = tmp_path / "global.yaml"
    global_path.write_text("""
base_branch: develop
""")
    monkeypatch.setattr("forger.config.GLOBAL_CONFIG_PATH", global_path)

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    forger_dir = project_dir / ".forger"
    forger_dir.mkdir()
    (forger_dir / "config.yaml").write_text("""
commands:
  test: "make test"
""")
    config = load_config(project_dir=project_dir)
    assert config.base_branch == "develop"
    assert config.commands["test"] == "make test"


# --- resolve_commands() stack-specific overrides ---


def _make_config_with_commands(commands):
    return ProjectConfig(commands=commands)


def test_resolve_commands_flat():
    cfg = _make_config_with_commands({"test": "pytest", "lint": "ruff check ."})
    assert cfg.resolve_commands() == {"test": "pytest", "lint": "ruff check ."}


def test_resolve_commands_stack_override():
    cfg = _make_config_with_commands(
        {
            "test": {
                "backend": "pytest backend/",
                "frontend": "vitest",
                "_default": "pytest",
            },
            "lint": "ruff check .",
        }
    )
    result = cfg.resolve_commands(stack="backend")
    assert result == {"test": "pytest backend/", "lint": "ruff check ."}


def test_resolve_commands_default_fallback():
    cfg = _make_config_with_commands(
        {
            "test": {
                "backend": "pytest backend/",
                "frontend": "vitest",
                "_default": "pytest",
            },
            "lint": "ruff check .",
        }
    )
    result = cfg.resolve_commands(stack="mobile")
    assert result == {"test": "pytest", "lint": "ruff check ."}


def test_resolve_commands_no_match():
    cfg = _make_config_with_commands(
        {
            "test": {"backend": "pytest backend/", "frontend": "vitest"},
            "lint": "ruff check .",
        }
    )
    result = cfg.resolve_commands(stack="mobile")
    assert result == {"lint": "ruff check ."}
    assert "test" not in result


# --- branch_prefix validator ---


def test_branch_prefix_empty_rejected():
    with pytest.raises(ValidationError, match="branch_prefix must be non-empty"):
        ProjectConfig(branch_prefix="")


def test_branch_prefix_whitespace_rejected():
    with pytest.raises(ValidationError, match="branch_prefix must be non-empty"):
        ProjectConfig(branch_prefix="  ")


# --- PipelineConfig ---


def test_pipeline_config_minimal():
    p = PipelineConfig(stages=["analyze", "implement"])
    assert p.stages == ["analyze", "implement"]
    assert p.models == {}
    assert p.tools == {}
    assert p.effort == {}
    assert p.timeout == {}


def test_pipeline_config_with_overrides():
    p = PipelineConfig(
        stages=["analyze", "implement"],
        models={"analyze": "opus"},
        timeout={"implement": 1800},
    )
    assert p.models["analyze"] == "opus"
    assert p.timeout["implement"] == 1800


def test_pipeline_config_stages_required():
    with pytest.raises(ValidationError):
        PipelineConfig()


# --- TimeoutConfig ---


def test_timeout_config_defaults():
    config = ProjectConfig()
    assert config.timeout.default == 900
    assert config.timeout.stages == {}


def test_timeout_config_per_stage():
    config = ProjectConfig(timeout={"default": 600, "stages": {"draft": 1200}})
    assert config.timeout.default == 600
    assert config.timeout.stages["draft"] == 1200


# --- Pipeline stages replace on merge ---


def test_deep_merge_pipeline_stages_replace():
    base = {
        "pipelines": {
            "sentry": {
                "stages": ["a", "b", "c"],
                "models": {"a": "opus"},
            }
        }
    }
    override = {
        "pipelines": {
            "sentry": {
                "stages": ["x", "y"],
            }
        }
    }
    result = _deep_merge(base, override)
    assert result["pipelines"]["sentry"]["stages"] == ["x", "y"]
    assert result["pipelines"]["sentry"]["models"] == {"a": "opus"}


def test_deep_merge_pipeline_models_merge():
    base = {
        "pipelines": {
            "sentry": {
                "stages": ["a", "b"],
                "models": {"a": "opus"},
            }
        }
    }
    override = {
        "pipelines": {
            "sentry": {
                "models": {"b": "haiku"},
            }
        }
    }
    result = _deep_merge(base, override)
    assert result["pipelines"]["sentry"]["stages"] == ["a", "b"]
    assert result["pipelines"]["sentry"]["models"] == {"a": "opus", "b": "haiku"}
