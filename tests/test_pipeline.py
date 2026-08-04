"""Tests for the pipeline topology module."""

from forger.pipeline import (
    EXTRA_STAGES,
    STAGE_BY_NAME,
    STAGE_NAMES,
    STAGES,
    STATE_LABEL,
    artifacts_for,
    next_stage,
    post_state_for,
    pre_state_for,
)


def test_stages_ordered():
    assert len(STAGES) == 10
    names = [s.name for s in STAGES]
    assert names[0] == "sentry_intake"
    assert names[-1] == "create_pr"


def test_no_duplicate_names():
    names = [s.name for s in STAGES]
    assert len(names) == len(set(names))


def test_no_duplicate_pre_states():
    pre_states = [s.pre_state for s in STAGES]
    assert len(pre_states) == len(set(pre_states))


def test_chain_is_continuous():
    """Each stage's post_state should be the next stage's pre_state."""
    for i in range(len(STAGES) - 1):
        assert STAGES[i].post_state == STAGES[i + 1].pre_state, (
            f"{STAGES[i].name}.post_state ({STAGES[i].post_state}) != "
            f"{STAGES[i + 1].name}.pre_state ({STAGES[i + 1].pre_state})"
        )


def test_next_stage():
    assert next_stage("triaged") == "analyze"
    assert next_stage("analyzed") == "prove"
    assert next_stage("drafted") == "push"
    assert next_stage("pushed") == "create_issue"
    assert next_stage("issue-created") == "create_pr"
    assert next_stage("pr-open") is None
    assert next_stage("nonexistent") is None


def test_post_state_for():
    assert post_state_for("analyze") == "analyzed"
    assert post_state_for("push") == "pushed"
    assert post_state_for("create_issue") == "issue-created"
    assert post_state_for("create_pr") == "pr-open"
    assert post_state_for("create_patch") == "patched"
    assert post_state_for("nonexistent") is None


def test_pre_state_for():
    assert pre_state_for("analyze") == "triaged"
    assert pre_state_for("push") == "drafted"
    assert pre_state_for("create_patch") == "drafted"
    assert pre_state_for("nonexistent") is None


def test_artifacts_for():
    assert artifacts_for("analyze") == ["analysis.md"]
    assert artifacts_for("draft") == [
        "issue.md",
        "commit.txt",
        "changelog.txt",
        "pr.md",
    ]
    assert artifacts_for("implement") == []
    assert artifacts_for("nonexistent") == []


def test_state_label():
    assert STATE_LABEL["triaged"] == "Triaged"
    assert STATE_LABEL["pushed"] == "Pushed"
    assert STATE_LABEL["issue-created"] == "Issue created"
    assert STATE_LABEL["pr-open"] == "PR open"
    assert STATE_LABEL["patched"] == "Patched"
    assert STATE_LABEL["parked"] == "Parked"


def test_stage_names():
    assert "analyze" in STAGE_NAMES
    assert "push" in STAGE_NAMES
    assert "create_patch" in STAGE_NAMES
    assert "create_issue" in STAGE_NAMES
    assert "create_pr" in STAGE_NAMES
    assert len(STAGE_NAMES) == len(STAGES) + len(EXTRA_STAGES)


def test_extra_stages_in_stage_by_name():
    assert "create_patch" in STAGE_BY_NAME
    assert STAGE_BY_NAME["create_patch"].post_state == "patched"
    assert STAGE_BY_NAME["create_patch"].needs_worktree is True


def test_needs_worktree():
    worktree_stages = {s.name for s in STAGES + EXTRA_STAGES if s.needs_worktree}
    assert "prove" in worktree_stages
    assert "implement" in worktree_stages
    assert "review" in worktree_stages
    assert "draft" in worktree_stages
    assert "create_patch" in worktree_stages
    assert "push" in worktree_stages
    assert "analyze" not in worktree_stages
    assert "create_issue" not in worktree_stages
    assert "create_pr" not in worktree_stages
