"""Tests for the pipeline topology module."""

from forger.pipeline import (
    STAGE_NAMES,
    STAGES,
    STATE_LABEL,
    artifacts_for,
    next_stage,
    post_state_for,
    pre_state_for,
)


def test_stages_ordered():
    assert len(STAGES) == 8
    names = [s.name for s in STAGES]
    assert names[0] == "sentry_intake"
    assert names[-1] == "push"


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
    assert next_stage("pr-open") is None
    assert next_stage("nonexistent") is None


def test_post_state_for():
    assert post_state_for("analyze") == "analyzed"
    assert post_state_for("push") == "pr-open"
    assert post_state_for("nonexistent") is None


def test_pre_state_for():
    assert pre_state_for("analyze") == "triaged"
    assert pre_state_for("push") == "drafted"
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
    assert STATE_LABEL["pr-open"] == "PR open"
    assert STATE_LABEL["parked"] == "Parked"


def test_stage_names():
    assert "analyze" in STAGE_NAMES
    assert "push" in STAGE_NAMES
    assert len(STAGE_NAMES) == len(STAGES)
