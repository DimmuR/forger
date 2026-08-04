"""Single source of truth for pipeline topology.

Every stage definition lives here. All consumers (orchestrator, CLI, etc.)
derive their views from STAGES.

Dynamic flow (per-run stage lists set by intake) is a future feature.
For v0.1.0 the pipeline is static and defined below.
"""

from dataclasses import dataclass, field

__all__ = [
    "EXTRA_STAGES",
    "STAGES",
    "STAGE_BY_NAME",
    "STAGE_BY_PRE_STATE",
    "STAGE_NAMES",
    "STATE_LABEL",
    "StageSpec",
    "VerifyCheck",
    "artifacts_for",
    "next_stage",
    "post_state_for",
    "pre_state_for",
    "resolve_pipeline_stages",
]


@dataclass(frozen=True)
class VerifyCheck:
    """Declarative post-condition for a stage's verify step."""

    required_files: tuple[str, ...] = ()
    """Files that must exist in run_dir."""

    evidence_checks: tuple[tuple[str, int], ...] = ()
    """(evidence_key, expected_exit_code) pairs."""

    gate_resolved: str | None = None
    """Gate key that must have a non-None resolved value."""


@dataclass(frozen=True)
class StageSpec:
    """One stage in the pipeline."""

    name: str
    """Module name used to resolve stage definition (e.g. 'analyze')."""

    pre_state: str
    """Pipeline state that triggers this stage (e.g. 'triaged')."""

    post_state: str
    """Pipeline state after successful completion (e.g. 'analyzed')."""

    label: str
    """Human-readable label for the post-state (e.g. 'Analyzed')."""

    artifacts: list[str] = field(default_factory=list)
    """Files/dirs this stage is expected to produce."""

    verify: VerifyCheck | None = None
    """Declarative verify check. If set, stages/__init__.py generates verify_fn from this
    instead of loading verify.py. Stages with custom verify.py (review, push) leave this None."""

    needs_worktree: bool = False
    """Whether this stage requires a worktree (code-modifying stages)."""


# Ordered list — the pipeline executes top to bottom.
STAGES: tuple[StageSpec, ...] = (
    StageSpec(
        name="sentry_intake",
        pre_state="intake",
        post_state="triaged",
        label="Triaged",
        artifacts=["change.md", "sentry-snapshot.json"],
        # Custom verify.py — intake creates change.md, verify confirms LLM set correct values
    ),
    StageSpec(
        name="analyze",
        pre_state="triaged",
        post_state="analyzed",
        label="Analyzed",
        artifacts=["analysis.md"],
        verify=VerifyCheck(required_files=("analysis.md",)),
    ),
    StageSpec(
        name="prove",
        pre_state="analyzed",
        post_state="proven",
        label="Proven",
        artifacts=["proof.md"],
        verify=VerifyCheck(
            required_files=("proof.md",),
            evidence_checks=(("proof_test", 1),),
        ),
        needs_worktree=True,
    ),
    StageSpec(
        name="fix_options",
        pre_state="proven",
        post_state="fix-chosen",
        label="Fix chosen",
        artifacts=["fix-options.md"],
        verify=VerifyCheck(
            required_files=("fix-options.md",),
            gate_resolved="fix_choice",
        ),
        needs_worktree=True,
    ),
    StageSpec(
        name="implement",
        pre_state="fix-chosen",
        post_state="fixed",
        label="Fixed",
        verify=VerifyCheck(
            evidence_checks=(("fix_verified", 0), ("lint", 0)),
        ),
        needs_worktree=True,
    ),
    StageSpec(
        name="review",
        pre_state="fixed",
        post_state="reviewed",
        label="Reviewed",
        artifacts=["reviews"],
        needs_worktree=True,
        # Custom verify.py — multi-reviewer consensus, review loopback
    ),
    StageSpec(
        name="draft",
        pre_state="reviewed",
        post_state="drafted",
        label="Drafted",
        artifacts=["issue.md", "commit.txt", "changelog.txt", "pr.md"],
        verify=VerifyCheck(
            required_files=("issue.md", "commit.txt", "changelog.txt", "pr.md"),
        ),
        needs_worktree=True,
    ),
    StageSpec(
        name="push",
        pre_state="drafted",
        post_state="pushed",
        label="Pushed",
        needs_worktree=True,
        # Custom verify.py — commit, push branch
    ),
    StageSpec(
        name="create_issue",
        pre_state="pushed",
        post_state="issue-created",
        label="Issue created",
        # Custom verify.py — create GitHub issue from issue.md
    ),
    StageSpec(
        name="create_pr",
        pre_state="issue-created",
        post_state="pr-open",
        label="PR open",
        # Custom verify.py — create draft PR from pr.md
    ),
)

# Stages not in the default pipeline but available for config-driven pipelines.
EXTRA_STAGES: tuple[StageSpec, ...] = (
    StageSpec(
        name="create_patch",
        pre_state="drafted",
        post_state="patched",
        label="Patched",
        needs_worktree=True,
        # Custom verify.py — git add -A, git diff --cached HEAD, write .patch
    ),
)

# --- Derived lookup tables (built once at import time) ---

_ALL_STAGES = STAGES + EXTRA_STAGES

STAGE_BY_NAME: dict[str, StageSpec] = {s.name: s for s in _ALL_STAGES}
"""Look up a StageSpec by its module name."""

STAGE_BY_PRE_STATE: dict[str, StageSpec] = {s.pre_state: s for s in STAGES}
"""Given a pipeline state, which stage runs next? (default pipeline only)"""

STATE_LABEL: dict[str, str] = {s.post_state: s.label for s in _ALL_STAGES}
"""Human-readable label for each post-state (plus terminal states below)."""
STATE_LABEL["parked"] = "Parked"


def next_stage(state: str) -> str | None:
    """Return the stage module name that should run after *state*, or None."""
    spec = STAGE_BY_PRE_STATE.get(state)
    return spec.name if spec else None


def post_state_for(stage_name: str) -> str | None:
    """Return the post-state for a stage name, or None if unknown."""
    spec = STAGE_BY_NAME.get(stage_name)
    return spec.post_state if spec else None


def pre_state_for(stage_name: str) -> str | None:
    """Return the pre-state for a stage name, or None if unknown."""
    spec = STAGE_BY_NAME.get(stage_name)
    return spec.pre_state if spec else None


def artifacts_for(stage_name: str) -> list[str]:
    """Return expected artifacts for a stage name."""
    spec = STAGE_BY_NAME.get(stage_name)
    return list(spec.artifacts) if spec else []


def resolve_pipeline_stages(stage_names: list[str]) -> list[StageSpec]:
    """Validate and resolve a list of stage names to StageSpec objects.

    Raises ValueError if any name is not in the registry.
    """
    specs = []
    for name in stage_names:
        spec = STAGE_BY_NAME.get(name)
        if spec is None:
            raise ValueError(f"Unknown stage '{name}' — not in registry")
        specs.append(spec)
    return specs


# All valid stage names (for CLI validation).
STAGE_NAMES: tuple[str, ...] = tuple(s.name for s in _ALL_STAGES)
