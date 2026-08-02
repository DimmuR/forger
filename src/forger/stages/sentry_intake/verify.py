"""Verify sentry intake stage: change.md exists with valid frontmatter.

Unlike other verifiers, intake does NOT use verify_stage(). Intake is special:
the LLM creates change.md and sets pipeline.stage (per run contract exception).
The verify module confirms the LLM set the right values rather than writing
the transition itself.
"""

from pathlib import Path

from forger.config import ProjectConfig
from forger.state import TERMINAL_STAGES, load_change


def verify(run_dir: Path, config: ProjectConfig) -> bool:
    change_path = run_dir / "change.md"
    if not change_path.exists():
        return False

    snapshot_path = run_dir / "sentry-snapshot.json"
    if not snapshot_path.exists():
        return False

    state, _body = load_change(change_path)

    if state.pipeline.stage in TERMINAL_STAGES or state.pipeline.parked_reason:
        return False

    if state.pipeline.stage != "triaged":
        print(
            f"  [sentry_intake/verify] expected stage 'triaged', "
            f"got '{state.pipeline.stage}'",
            flush=True,
        )
        return False

    return True
