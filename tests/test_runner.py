import pytest

from forger.config import (
    BUILTIN_DEFAULTS,
    PipelineConfig,
    ProjectConfig,
    RunnerTemplate,
)
from forger.runner import (
    invoke_runner,
    resolve_effort,
    resolve_model,
    resolve_runner,
    resolve_timeout,
    resolve_tools,
)


def test_resolve_model_default():
    config = ProjectConfig.model_validate(BUILTIN_DEFAULTS)
    assert resolve_model("implement", config) == "sonnet"
    assert resolve_model("review", config) == "opus"
    assert resolve_model("sentry_intake", config) == "opus"
    assert resolve_model("unknown_stage", config) == "sonnet"


def test_resolve_runner_default():
    config = ProjectConfig.model_validate(BUILTIN_DEFAULTS)
    runner = resolve_runner(config)
    assert "claude" in runner.command


def test_invoke_runner_success(tmp_path):
    template = RunnerTemplate(command="echo done", timeout=10)
    result = invoke_runner(template, "test prompt", tmp_path, "sonnet", timeout=10)
    assert result.exit_code == 0
    assert not result.timed_out
    assert result.duration_seconds < 10


def test_invoke_runner_failure(tmp_path):
    template = RunnerTemplate(command="false", timeout=10)
    result = invoke_runner(template, "test prompt", tmp_path, "sonnet", timeout=10)
    assert result.exit_code == 1
    assert not result.timed_out


def test_invoke_runner_timeout(tmp_path):
    template = RunnerTemplate(command="sleep 30", timeout=2)
    result = invoke_runner(template, "test prompt", tmp_path, "sonnet", timeout=2)
    assert result.timed_out
    assert result.exit_code == -1


def test_invoke_runner_template_substitution(tmp_path):
    template = RunnerTemplate(
        command="echo {model} {prompt_arg} {workdir}",
        timeout=10,
    )
    result = invoke_runner(template, "test prompt", tmp_path, "opus", timeout=10)
    assert result.exit_code == 0


def test_invoke_runner_env_vars(tmp_path):
    template = RunnerTemplate(
        command="echo $TEST_VAR",
        env={"TEST_VAR": "hello-{model}"},
        timeout=10,
    )
    result = invoke_runner(template, "test prompt", tmp_path, "sonnet", timeout=10)
    assert result.exit_code == 0


def test_invoke_runner_rejects_shell_injection_in_model(tmp_path):
    template = RunnerTemplate(command="echo {model}", timeout=10)
    with pytest.raises(ValueError):
        invoke_runner(template, "test prompt", tmp_path, "sonnet; rm -rf /", timeout=10)


def test_invoke_runner_rejects_backticks_in_model(tmp_path):
    template = RunnerTemplate(command="echo {model}", timeout=10)
    with pytest.raises(ValueError):
        invoke_runner(template, "test prompt", tmp_path, "sonnet`whoami`", timeout=10)


def test_invoke_runner_rejects_pipe_in_allowed_tools(tmp_path):
    template = RunnerTemplate(command="echo {allowed_tools}", timeout=10)
    with pytest.raises(ValueError):
        invoke_runner(
            template,
            "test prompt",
            tmp_path,
            "sonnet",
            allowed_tools=["Read|evil"],
            timeout=10,
        )


def test_invoke_runner_rejects_unsafe_env_value(tmp_path):
    template = RunnerTemplate(
        command="echo hello",
        env={"VAR": "value|with|pipes"},
        timeout=10,
    )
    with pytest.raises(ValueError, match="Runner env variable"):
        invoke_runner(template, "test prompt", tmp_path, "sonnet", timeout=10)


def test_invoke_runner_accepts_safe_model_values(tmp_path):
    template = RunnerTemplate(command="echo {model}", timeout=10)
    result = invoke_runner(
        template, "test prompt", tmp_path, "claude-3-opus", timeout=10
    )
    assert result.exit_code == 0


# --- 4-layer pipeline resolution ---


def _config_with_globals():
    return ProjectConfig.model_validate(BUILTIN_DEFAULTS)


def _pipeline(**kwargs):
    return PipelineConfig(stages=["analyze", "implement"], **kwargs)


class TestResolveModel4Layer:
    def test_global_default(self):
        config = _config_with_globals()
        assert resolve_model("unknown", config) == "sonnet"

    def test_global_per_stage(self):
        config = _config_with_globals()
        assert resolve_model("review", config) == "opus"

    def test_pipeline_per_stage_wins(self):
        config = _config_with_globals()
        p = _pipeline(models={"review": "haiku"})
        assert resolve_model("review", config, p) == "haiku"

    def test_pipeline_none_falls_through(self):
        config = _config_with_globals()
        p = _pipeline()
        assert resolve_model("review", config, p) == "opus"


class TestResolveTools4Layer:
    def test_global_default(self):
        config = _config_with_globals()
        assert resolve_tools("unknown", config) == ["Read", "Write", "Edit", "Bash"]

    def test_global_per_stage(self):
        config = _config_with_globals()
        assert resolve_tools("review", config) == ["Read", "Write", "Edit"]

    def test_pipeline_per_stage_wins(self):
        config = _config_with_globals()
        p = _pipeline(tools={"review": ["Read"]})
        assert resolve_tools("review", config, p) == ["Read"]


class TestResolveEffort4Layer:
    def test_global_default_none(self):
        config = _config_with_globals()
        assert resolve_effort("unknown", config) is None

    def test_pipeline_per_stage(self):
        config = _config_with_globals()
        p = _pipeline(effort={"analyze": "high"})
        assert resolve_effort("analyze", config, p) == "high"


class TestResolveTimeout:
    def test_global_default(self):
        config = _config_with_globals()
        assert resolve_timeout("unknown", config) == 900

    def test_global_per_stage(self):
        config = ProjectConfig(timeout={"default": 900, "stages": {"draft": 1800}})
        assert resolve_timeout("draft", config) == 1800

    def test_pipeline_per_stage_wins(self):
        config = ProjectConfig(timeout={"default": 900, "stages": {"draft": 1800}})
        p = _pipeline(timeout={"draft": 3600})
        assert resolve_timeout("draft", config, p) == 3600

    def test_pipeline_none_falls_through(self):
        config = ProjectConfig(timeout={"default": 900, "stages": {"draft": 1800}})
        p = _pipeline()
        assert resolve_timeout("draft", config, p) == 1800
