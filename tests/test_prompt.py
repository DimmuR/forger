from pathlib import Path

from forger.config import BUILTIN_DEFAULTS, ProjectConfig
from forger.prompt import render_prompt
from forger.stages import StageDef
from tests import make_state


def _make_stage(tmp_path: Path) -> StageDef:
    stage_dir = tmp_path / "stages" / "analyze"
    stage_dir.mkdir(parents=True)
    (stage_dir / "prompt.md").write_text("# Analyze\n\nFind the root cause.\n")
    refs_dir = stage_dir / "references"
    refs_dir.mkdir()
    (refs_dir / "analysis-format.md").write_text("Use structured headings.\n")
    return StageDef(
        name="analyze",
        path=stage_dir,
        prompt_path=stage_dir / "prompt.md",
        references=[refs_dir / "analysis-format.md"],
    )


def test_render_contains_prompt(tmp_path):
    stage_def = _make_stage(tmp_path)
    config = ProjectConfig.model_validate(BUILTIN_DEFAULTS)
    state = make_state(stage="analyze")
    result = render_prompt(
        stage_def, state, config, tmp_path / "run", tmp_path / "repo", tmp_path
    )
    assert "# Analyze" in result
    assert "Find the root cause." in result


def test_render_contains_references(tmp_path):
    stage_def = _make_stage(tmp_path)
    config = ProjectConfig.model_validate(BUILTIN_DEFAULTS)
    state = make_state(stage="analyze")
    result = render_prompt(
        stage_def, state, config, tmp_path / "run", tmp_path / "repo", tmp_path
    )
    assert "analysis-format.md" in result
    assert "Use structured headings." in result


def test_render_contains_run_contract(tmp_path):
    stage_def = _make_stage(tmp_path)
    config = ProjectConfig.model_validate(BUILTIN_DEFAULTS)
    state = make_state(stage="analyze")
    result = render_prompt(
        stage_def, state, config, tmp_path / "run", tmp_path / "repo", tmp_path
    )
    assert "Run Contract" in result


def test_render_contains_context_block(tmp_path):
    stage_def = _make_stage(tmp_path)
    config = ProjectConfig.model_validate(BUILTIN_DEFAULTS)
    config.commands = {"test": "pytest", "lint": "ruff check ."}
    state = make_state(stage="analyze")
    run_dir = tmp_path / "run"
    repo_dir = tmp_path / "repo"
    result = render_prompt(stage_def, state, config, run_dir, repo_dir, tmp_path)
    assert "Run Context" in result
    assert "sentry-TEST-001" in result
    assert str(run_dir) in result
    assert str(repo_dir) in result
    assert "analyze" in result
    assert "`pytest`" in result
    assert "`ruff check .`" in result


def test_render_no_flow_in_context(tmp_path):
    """Flow field was removed; verify it no longer appears in rendered prompts."""
    stage_def = _make_stage(tmp_path)
    config = ProjectConfig.model_validate(BUILTIN_DEFAULTS)
    state = make_state(stage="analyze")
    result = render_prompt(
        stage_def, state, config, tmp_path / "run", tmp_path / "repo", tmp_path
    )
    assert "Flow:" not in result
