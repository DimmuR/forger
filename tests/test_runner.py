import pytest

from forger.config import BUILTIN_DEFAULTS, ProjectConfig, RunnerTemplate
from forger.runner import invoke_runner, resolve_model, resolve_runner


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
