"""Tests for the orchestration loop using a fake runner."""

import stat
import sys
from pathlib import Path

import pytest

from forger.config import BUILTIN_DEFAULTS, ProjectConfig, RunnerTemplate
from forger.orchestrator import (
    ensure_run_dir,
    find_run_dir,
    reset_to_stage,
    run_pipeline,
)
from forger.state import (
    ChangeState,
    PipelineState,
    load_change,
    save_change,
)


@pytest.fixture
def config(tmp_path):
    """Config with a fake runner that executes a script."""
    cfg = ProjectConfig.model_validate(BUILTIN_DEFAULTS)
    cfg.runners["claude"] = RunnerTemplate(
        command="bash {prompt_arg}",
        timeout=30,
    )
    cfg.commands = {"test": "echo test", "lint": "echo lint"}
    cfg.worktree = False  # Tests don't have git repos
    return cfg


@pytest.fixture
def project_dir(tmp_path):
    """Set up a fake project with .forger structure."""
    forger_dir = tmp_path / ".forger"
    forger_dir.mkdir()
    (forger_dir / "artifacts" / "sentry").mkdir(parents=True)
    return tmp_path


_PYTHON = sys.executable


def _stage_script(run_dir: Path, stage: str) -> str:
    """Return bash script content that simulates a stage's output."""
    src_path = Path(__file__).parent.parent / "src"
    scripts = {
        "sentry_intake": f"""#!/bin/bash
cat > {run_dir}/change.md << 'EOF'
---
id: sentry-TEST-001
title: "Test bug"
origin: sentry
created: "2026-07-18"
updated: "2026-07-18"
pipeline:
  stage: triaged
gates: {{}}
evidence: {{}}
---

Test bug description.
EOF
""",
        "analyze": f"""#!/bin/bash
cat > {run_dir}/analysis.md << 'EOF'
# Root Cause
Found the bug at foo.py:42.
EOF
""",
        "prove": f"""#!/bin/bash
cat > {run_dir}/proof.md << 'EOF'
# Proof
Test written and fails.
EOF
{_PYTHON} -c "
import sys; sys.path.insert(0, '{src_path}')
from forger.state import load_change, save_change, EvidenceEntry
from pathlib import Path
state, body = load_change(Path('{run_dir}/change.md'))
state.evidence['proof_test'] = EvidenceEntry(path='tests/test_bug.py::test_it', exit_code=1, last_run='2026-07-18')
save_change(Path('{run_dir}/change.md'), state, body)
"
""",
        "fix_options": f"""#!/bin/bash
cat > {run_dir}/fix-options.md << 'EOF'
# Fix Options
Option a: minimal fix.
EOF
{_PYTHON} -c "
import sys; sys.path.insert(0, '{src_path}')
from forger.state import load_change, save_change, Gate
from pathlib import Path
state, body = load_change(Path('{run_dir}/change.md'))
state.gates['fix_choice'] = Gate(required=False, resolved='a', rationale='auto: quick-win')
save_change(Path('{run_dir}/change.md'), state, body)
"
""",
        "implement": f"""#!/bin/bash
{_PYTHON} -c "
import sys; sys.path.insert(0, '{src_path}')
from forger.state import load_change, save_change, EvidenceEntry
from pathlib import Path
state, body = load_change(Path('{run_dir}/change.md'))
state.evidence['fix_verified'] = EvidenceEntry(exit_code=0, last_run='2026-07-18')
state.evidence['lint'] = EvidenceEntry(exit_code=0, last_run='2026-07-18')
save_change(Path('{run_dir}/change.md'), state, body)
"
""",
        "review": f"""#!/bin/bash
mkdir -p {run_dir}/reviews
cat > {run_dir}/reviews/review-1-quality.md << 'EOF'
# Review 1
No findings.
**Verdict: accepted**
EOF
""",
        "draft": f"""#!/bin/bash
echo '# Test bug fix' > {run_dir}/issue.md
echo 'fix: resolve test bug' > {run_dir}/commit.txt
echo 'Fixed test bug.' > {run_dir}/changelog.txt
echo '# Fix test bug' > {run_dir}/pr.md
""",
    }
    return scripts.get(stage, "#!/bin/bash\nexit 0")


def _write_fake_runner_script(run_dir: Path, stage: str) -> str:
    """Write a bash script that simulates a stage's output. Returns script content."""
    return _stage_script(run_dir, stage)


def _write_stage_dispatcher(run_dir: Path, stages: list[str]) -> Path:
    """Write per-stage scripts and a dispatcher. Returns dispatcher path."""
    src_path = Path(__file__).parent.parent / "src"
    scripts_dir = run_dir / "_scripts"
    scripts_dir.mkdir(exist_ok=True)

    for stage in stages:
        script_path = scripts_dir / f"{stage}.sh"
        script_path.write_text(_stage_script(run_dir, stage))
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

    dispatcher = scripts_dir / "dispatch.sh"
    dispatcher.write_text(f"""#!/bin/bash
PYTHONPATH="{src_path}" {_PYTHON} -c "
from forger.state import load_change
from forger.pipeline import next_stage
from pathlib import Path
change = Path('{run_dir}/change.md')
if not change.exists():
    print('sentry_intake')
else:
    state, _ = load_change(change)
    stage = next_stage(state.pipeline.stage)
    print(stage or 'none')
" | while read stage; do
    script="{scripts_dir}/$stage.sh"
    if [ -f "$script" ]; then
        bash "$script"
    fi
done
""")
    dispatcher.chmod(dispatcher.stat().st_mode | stat.S_IEXEC)
    return dispatcher


def test_ensure_run_dir(project_dir):
    run_dir = ensure_run_dir("sentry", "TEST-001", project_dir)
    assert run_dir.exists()
    assert "sentry" in str(run_dir)
    assert "run-TEST-001" in str(run_dir)


def test_find_run_dir(project_dir):
    run_dir = ensure_run_dir("sentry", "TEST-001", project_dir)
    save_change(
        run_dir / "change.md",
        ChangeState(
            id="sentry-TEST-001",
            title="Test",
            origin="sentry",
            created="2026-07-18",
            updated="2026-07-18",
            pipeline=PipelineState(stage="triaged"),
        ),
        "body",
    )
    found = find_run_dir("TEST-001", project_dir)
    assert found == run_dir


def test_find_run_dir_not_found(project_dir):
    found = find_run_dir("NONEXISTENT", project_dir)
    assert found is None


def test_reset_to_stage(project_dir):
    run_dir = ensure_run_dir("sentry", "TEST-RESET", project_dir)
    state = ChangeState(
        id="sentry-TEST-RESET",
        title="Test bug",
        origin="sentry",
        created="2026-07-18",
        updated="2026-07-18",
        pipeline=PipelineState(
            stage="reviewed",
            parked_reason="Some reason",
        ),
    )
    save_change(run_dir / "change.md", state, "body")
    (run_dir / "analysis.md").write_text("analysis")
    reviews_dir = run_dir / "reviews"
    reviews_dir.mkdir()
    (reviews_dir / "review-1-quality.md").write_text("review")

    new_stage = reset_to_stage(run_dir, "implement")
    assert new_stage == "fix-chosen"

    reloaded, _ = load_change(run_dir / "change.md")
    assert reloaded.pipeline.stage == "fix-chosen"
    assert reloaded.pipeline.parked_reason is None
    # analysis.md not deleted (belongs to analyze, not implement)
    assert (run_dir / "analysis.md").exists()


def test_orchestrator_single_stage(project_dir, config):
    """Test that orchestrator can advance one stage with a fake runner."""
    run_dir = ensure_run_dir("sentry", "TEST-001", project_dir)

    # Pre-create change.md at triaged stage
    state = ChangeState(
        id="sentry-TEST-001",
        title="Test bug",
        origin="sentry",
        created="2026-07-18",
        updated="2026-07-18",
        pipeline=PipelineState(stage="triaged"),
    )
    save_change(run_dir / "change.md", state, "Test bug description.")

    # Use a runner that creates analysis.md
    script = _write_fake_runner_script(run_dir, "analyze")
    script_path = run_dir / "runner.sh"
    script_path.write_text(script)
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

    config.runners["claude"] = RunnerTemplate(command=f"bash {script_path}", timeout=30)

    outcome = run_pipeline(
        source="sentry",
        issue_id="TEST-001",
        config=config,
        project_dir=project_dir,
        repo_dir=project_dir,
    )

    # Should have advanced at least one stage
    assert outcome.stages_executed >= 1
    final_state, _ = load_change(run_dir / "change.md")
    assert final_state.pipeline.stage == "analyzed"


def test_orchestrator_static_topology(project_dir, config):
    """Test that pipeline topology is driven by STAGES, not per-run state."""
    run_dir = ensure_run_dir("sentry", "TEST-003", project_dir)

    state = ChangeState(
        id="sentry-TEST-003",
        title="Test bug",
        origin="sentry",
        created="2026-07-18",
        updated="2026-07-18",
        pipeline=PipelineState(stage="triaged"),
    )
    save_change(run_dir / "change.md", state, "Test.")

    # Runner creates analysis.md (the analyze stage artifact)
    script = f"""#!/bin/bash
cat > {run_dir}/analysis.md << 'EOF'
# Root Cause
Bug at foo.py:42.
EOF
"""
    script_path = run_dir / "runner.sh"
    script_path.write_text(script)
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

    config.runners["claude"] = RunnerTemplate(command=f"bash {script_path}", timeout=30)

    outcome = run_pipeline(
        source="sentry",
        issue_id="TEST-003",
        config=config,
        project_dir=project_dir,
        repo_dir=project_dir,
    )

    # Pipeline should advance based on the static STAGES definition
    final_state, _ = load_change(run_dir / "change.md")
    assert final_state.pipeline.stage == "analyzed"
    assert outcome.stages_executed >= 1


def test_orchestrator_parked_stops_cleanly(project_dir, config):
    """Test that pipeline stops cleanly when LLM parks the run."""
    run_dir = ensure_run_dir("sentry", "TEST-004", project_dir)

    state = ChangeState(
        id="sentry-TEST-004",
        title="Test deep",
        origin="sentry",
        created="2026-07-18",
        updated="2026-07-18",
        pipeline=PipelineState(
            stage="analyzed",
            parked_reason="Cannot reproduce without live Redis",
        ),
    )
    save_change(run_dir / "change.md", state, "Test.")

    outcome = run_pipeline(
        source="sentry",
        issue_id="TEST-004",
        config=config,
        project_dir=project_dir,
        repo_dir=project_dir,
    )

    assert outcome.blocked_reason is not None
    assert "Parked" in outcome.blocked_reason
    assert outcome.final_stage == "analyzed"


def test_orchestrator_gate_blocks(project_dir, config):
    """Test that unresolved gate blocks the pipeline."""
    run_dir = ensure_run_dir("sentry", "TEST-002", project_dir)

    state = ChangeState(
        id="sentry-TEST-002",
        title="Test bug 2",
        origin="sentry",
        created="2026-07-18",
        updated="2026-07-18",
        pipeline=PipelineState(stage="proven"),
    )
    save_change(run_dir / "change.md", state, "Test.")

    # Runner writes fix-options but leaves gate unresolved
    src_path = Path(__file__).parent.parent / "src"
    script = (
        f"#!/bin/bash\n"
        f"cat > {run_dir}/fix-options.md << 'FIXEOF'\n"
        f"# Options\n"
        f"a: fast fix\n"
        f"b: proper fix\n"
        f"FIXEOF\n"
        f'PYTHONPATH="{src_path}" {_PYTHON} -c "\n'
        f"from forger.state import load_change, save_change, Gate\n"
        f"from pathlib import Path\n"
        f"state, body = load_change(Path('{run_dir}/change.md'))\n"
        f"state.gates['fix_choice'] = Gate(required=True, resolved=None)\n"
        f"save_change(Path('{run_dir}/change.md'), state, body)\n"
        f'"\n'
    )
    script_path = run_dir / "runner.sh"
    script_path.write_text(script)
    script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)

    config.runners["claude"] = RunnerTemplate(command=f"bash {script_path}", timeout=30)

    outcome = run_pipeline(
        source="sentry",
        issue_id="TEST-002",
        config=config,
        project_dir=project_dir,
        repo_dir=project_dir,
    )

    assert outcome.blocked_reason is not None
    assert outcome.stages_executed == 1  # fix_options ran but didn't advance


def test_orchestrator_multi_stage_run(project_dir, config):
    """Integration test: run analyze → prove → fix_options → implement → review → draft."""
    run_dir = ensure_run_dir("sentry", "TEST-MULTI", project_dir)

    state = ChangeState(
        id="sentry-TEST-MULTI",
        title="Test bug",
        origin="sentry",
        created="2026-07-18",
        updated="2026-07-18",
        pipeline=PipelineState(stage="triaged"),
    )
    save_change(run_dir / "change.md", state, "Test bug description.")

    stages = ["analyze", "prove", "fix_options", "implement", "review", "draft"]
    dispatcher = _write_stage_dispatcher(run_dir, stages)
    config.runners["claude"] = RunnerTemplate(command=f"bash {dispatcher}", timeout=30)

    outcome = run_pipeline(
        source="sentry",
        issue_id="TEST-MULTI",
        config=config,
        project_dir=project_dir,
        repo_dir=project_dir,
        until_stage="draft",
    )

    assert outcome.stages_executed == 6
    final_state, _ = load_change(run_dir / "change.md")
    assert final_state.pipeline.stage == "drafted"
    assert (run_dir / "analysis.md").exists()
    assert (run_dir / "proof.md").exists()
    assert (run_dir / "fix-options.md").exists()
    assert (run_dir / "issue.md").exists()
    assert (run_dir / "commit.txt").exists()
    assert (run_dir / "pr.md").exists()
    assert final_state.evidence["proof_test"].exit_code == 1
    assert final_state.evidence["fix_verified"].exit_code == 0
    assert final_state.evidence["lint"].exit_code == 0
    assert final_state.gates["fix_choice"].resolved == "a"
