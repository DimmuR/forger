"""Global + project config loading with merge precedence."""

__all__ = [
    "BUILTIN_DEFAULTS",
    "GLOBAL_CONFIG_PATH",
    "ModelConfig",
    "PipelineConfig",
    "ProjectConfig",
    "ReviewConfig",
    "ReviewerDef",
    "RunnerTemplate",
    "TimeoutConfig",
    "ToolsConfig",
    "load_config",
]

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class RunnerTemplate(BaseModel):
    command: str
    env: dict[str, str] = Field(default_factory=dict)
    timeout: int = 900


class ToolsConfig(BaseModel):
    default: list[str] = ["Read", "Write", "Edit", "Bash"]
    stages: dict[str, list[str]] = {}


class EffortConfig(BaseModel):
    default: str | None = None
    stages: dict[str, str] = {}


class TimeoutConfig(BaseModel):
    default: int = 900
    stages: dict[str, int] = {}


class ModelConfig(BaseModel):
    default: str = "sonnet"
    stages: dict[str, str] = {}


class ReviewerDef(BaseModel):
    role: str = "quality"
    runner: str | None = None
    model: str | None = None


class ReviewConfig(BaseModel):
    consensus: str = "all"
    reviewers: list[ReviewerDef] = [ReviewerDef()]
    max_loops: int = 2


class PipelineConfig(BaseModel):
    stages: list[str]
    models: dict[str, str] = {}
    tools: dict[str, list[str]] = {}
    effort: dict[str, str] = {}
    timeout: dict[str, int] = {}


class ProjectConfig(BaseModel):
    models: ModelConfig = ModelConfig()
    effort: EffortConfig = EffortConfig()
    timeout: TimeoutConfig = TimeoutConfig()
    tools: ToolsConfig = ToolsConfig()
    runners: dict[str, RunnerTemplate] = {}
    default_runner: str = "claude"
    review: ReviewConfig = ReviewConfig()
    pipelines: dict[str, PipelineConfig] = {}
    commands: dict[str, str | dict[str, str]] = {}
    worktree: bool = True
    base_branch: str = "main"
    branch_prefix: str = "forger"
    gh_account: str | None = None

    @field_validator("branch_prefix")
    @classmethod
    def _branch_prefix_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("branch_prefix must be non-empty")
        return v

    def resolve_commands(self, stack: str | None = None) -> dict[str, str]:
        """Resolve commands for a stack. Stack-specific overrides flat values."""
        resolved = {}
        for key, val in self.commands.items():
            if isinstance(val, str):
                resolved[key] = val
            elif isinstance(val, dict) and stack and stack in val:
                resolved[key] = val[stack]
            elif isinstance(val, dict) and "_default" in val:
                resolved[key] = val["_default"]
        return resolved


BUILTIN_DEFAULTS: dict[str, Any] = {
    # The "default" keys below duplicate model defaults (e.g. ModelConfig.default = "sonnet").
    # This is intentional: _deep_merge needs a complete base dict to merge user overrides
    # into. Without "default" here, a user config with only "stages:" would drop the default.
    "models": {
        "default": "sonnet",
        "stages": {
            "sentry_intake": "opus",
            "analyze": "sonnet",
            "prove": "sonnet",
            "fix_options": "sonnet",
            "implement": "sonnet",
            "review": "opus",
            "draft": "sonnet",
        },
    },
    "timeout": {
        "default": 900,
        "stages": {},
    },
    "tools": {
        "default": ["Read", "Write", "Edit", "Bash"],
        "stages": {
            "sentry_intake": ["Read", "Write", "Edit", "Bash", "mcp__sentry"],
            "review": ["Read", "Write", "Edit"],
            "draft": ["Read", "Write", "Edit"],
        },
    },
    "runners": {
        "claude": {
            "command": "claude -p {prompt_arg} --model {model} --allowedTools {allowed_tools} --output-format stream-json --verbose{effort}",
            "env": {"CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": "0"},
            "timeout": 900,
        },
        "goose": {
            "command": "goose run --no-session --with-builtin developer -t {prompt_arg}",
            "env": {
                "GOOSE_PROVIDER": "ollama",
                "GOOSE_MODEL": "{model}",
            },
            "timeout": 900,
        },
    },
    "default_runner": "claude",
    "pipelines": {
        "sentry": {
            "stages": [
                "sentry_intake",
                "analyze",
                "prove",
                "fix_options",
                "implement",
                "review",
                "draft",
                "push",
                "create_issue",
                "create_pr",
            ],
        },
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base. Override wins on conflicts.

    Lists replace rather than merge — a pipeline's ``stages`` list is always
    explicit, never appended to.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, return empty dict if missing."""
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


GLOBAL_CONFIG_PATH = Path.home() / ".forger" / "config.yaml"


def load_config(project_dir: Path | None = None) -> ProjectConfig:
    """Load config with precedence: built-in → global → project."""
    merged = BUILTIN_DEFAULTS.copy()
    merged = _deep_merge(merged, _load_yaml(GLOBAL_CONFIG_PATH))
    if project_dir:
        project_config_path = project_dir / ".forger" / "config.yaml"
        merged = _deep_merge(merged, _load_yaml(project_config_path))
    return ProjectConfig.model_validate(merged)
