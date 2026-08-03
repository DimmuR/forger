"""Tests for stage verify modules."""

from pathlib import Path

import pytest

from forger.stages import load_verify, resolve_stage
from forger.state import (
    ChangeState,
    EvidenceEntry,
    Gate,
    load_change,
    save_change,
)
from tests import make_state


@pytest.fixture
def base_state():
    return make_state(stage="triaged")


def _write_change(run_dir: Path, state: ChangeState, body: str = "Test issue."):
    save_change(run_dir / "change.md", state, body)


# --- Analyze verify ---


def test_analyze_verify_advances(tmp_path, config, base_state):
    base_state.pipeline.stage = "triaged"
    _write_change(tmp_path, base_state)
    (tmp_path / "analysis.md").write_text("# Root cause\nFound it.")

    stage_def = resolve_stage("analyze", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is True

    from forger.state import load_change

    state, _ = load_change(tmp_path / "change.md")
    assert state.pipeline.stage == "analyzed"


def test_analyze_verify_missing_artifact(tmp_path, config, base_state):
    base_state.pipeline.stage = "triaged"
    _write_change(tmp_path, base_state)

    stage_def = resolve_stage("analyze", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is False


# --- Prove verify ---


def test_prove_verify_advances(tmp_path, config, base_state):
    base_state.pipeline.stage = "analyzed"
    base_state.evidence["proof_test"] = EvidenceEntry(
        path="tests/test_bug.py::test_it", exit_code=1, last_run="2026-07-18"
    )
    _write_change(tmp_path, base_state)
    (tmp_path / "proof.md").write_text("# Proof\nTest fails as expected.")

    stage_def = resolve_stage("prove", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is True

    from forger.state import load_change

    state, _ = load_change(tmp_path / "change.md")
    assert state.pipeline.stage == "proven"


def test_prove_verify_wrong_exit_code(tmp_path, config, base_state):
    base_state.pipeline.stage = "analyzed"
    base_state.evidence["proof_test"] = EvidenceEntry(
        path="tests/test_bug.py::test_it", exit_code=0, last_run="2026-07-18"
    )
    _write_change(tmp_path, base_state)
    (tmp_path / "proof.md").write_text("# Proof\nTest passes — wrong.")

    stage_def = resolve_stage("prove", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is False


# --- Fix options verify ---


def test_fix_options_verify_resolved(tmp_path, config, base_state):
    base_state.pipeline.stage = "proven"
    base_state.gates["fix_choice"] = Gate(
        required=False, resolved="a", rationale="auto"
    )
    _write_change(tmp_path, base_state)
    (tmp_path / "fix-options.md").write_text("# Options\nOption a: minimal fix.")

    stage_def = resolve_stage("fix_options", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is True

    from forger.state import load_change

    state, _ = load_change(tmp_path / "change.md")
    assert state.pipeline.stage == "fix-chosen"


def test_fix_options_verify_gate_unresolved(tmp_path, config, base_state):
    base_state.pipeline.stage = "proven"
    base_state.gates["fix_choice"] = Gate(required=True, resolved=None)
    _write_change(tmp_path, base_state)
    (tmp_path / "fix-options.md").write_text("# Options\nNeed human input.")

    stage_def = resolve_stage("fix_options", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is False


# --- Implement verify ---


def test_implement_verify_advances(tmp_path, config, base_state):
    base_state.pipeline.stage = "fix-chosen"
    base_state.evidence["fix_verified"] = EvidenceEntry(
        exit_code=0, last_run="2026-07-18"
    )
    base_state.evidence["lint"] = EvidenceEntry(exit_code=0, last_run="2026-07-18")
    _write_change(tmp_path, base_state)

    stage_def = resolve_stage("implement", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is True

    from forger.state import load_change

    state, _ = load_change(tmp_path / "change.md")
    assert state.pipeline.stage == "fixed"


def test_implement_verify_lint_failed(tmp_path, config, base_state):
    base_state.pipeline.stage = "fix-chosen"
    base_state.evidence["fix_verified"] = EvidenceEntry(
        exit_code=0, last_run="2026-07-18"
    )
    base_state.evidence["lint"] = EvidenceEntry(exit_code=1, last_run="2026-07-18")
    _write_change(tmp_path, base_state)

    stage_def = resolve_stage("implement", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is False


# --- Review verify ---


def test_review_verify_accepted(tmp_path, config, base_state):
    base_state.pipeline.stage = "fixed"
    _write_change(tmp_path, base_state)
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir()
    (reviews_dir / "review-1-quality.md").write_text(
        "# Review\nNo findings.\n**Verdict: accepted**"
    )

    stage_def = resolve_stage("review", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is True

    from forger.state import load_change

    state, _ = load_change(tmp_path / "change.md")
    assert state.pipeline.stage == "reviewed"


def test_review_verify_no_reviews_dir(tmp_path, config, base_state):
    base_state.pipeline.stage = "fixed"
    _write_change(tmp_path, base_state)

    stage_def = resolve_stage("review", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is False


def test_review_verify_wrong_pre_state(tmp_path, config, base_state):
    base_state.pipeline.stage = "triaged"
    _write_change(tmp_path, base_state)
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir()
    (reviews_dir / "review-1-quality.md").write_text("# Review\n**Verdict: accepted**")

    stage_def = resolve_stage("review", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is False


def test_review_rejection_loops_back(tmp_path, config, base_state):
    base_state.pipeline.stage = "fixed"
    _write_change(tmp_path, base_state)
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir()
    (reviews_dir / "review-1-quality.md").write_text(
        "# Review\nBad code.\n**Verdict: changes_requested**"
    )

    stage_def = resolve_stage("review", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is True

    from forger.state import load_change

    state, _ = load_change(tmp_path / "change.md")
    assert state.pipeline.stage == "fix-chosen"
    assert (reviews_dir / "review-1-feedback.md").exists()


def test_review_max_loops_parks(tmp_path, config, base_state):
    config.review.max_loops = 2
    base_state.pipeline.stage = "fixed"
    _write_change(tmp_path, base_state)
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir()
    # Simulate round 1 already happened (feedback file exists)
    (reviews_dir / "review-1-feedback.md").write_text("# Feedback round 1")
    # Round 2 review also rejects
    (reviews_dir / "review-2-quality.md").write_text(
        "# Review\nStill bad.\n**Verdict: changes_requested**"
    )

    stage_def = resolve_stage("review", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is False

    from forger.state import load_change

    state, _ = load_change(tmp_path / "change.md")
    assert state.pipeline.parked_reason is not None
    assert "loop exceeded" in state.pipeline.parked_reason.lower()


def test_review_majority_consensus(tmp_path, base_state):
    from forger.config import BUILTIN_DEFAULTS, ProjectConfig, ReviewerDef

    cfg = ProjectConfig.model_validate(BUILTIN_DEFAULTS)
    cfg.review.consensus = "majority"
    cfg.review.reviewers = [
        ReviewerDef(role="quality"),
        ReviewerDef(role="challenge"),
        ReviewerDef(role="security"),
    ]

    base_state.pipeline.stage = "fixed"
    _write_change(tmp_path, base_state)
    reviews_dir = tmp_path / "reviews"
    reviews_dir.mkdir()
    (reviews_dir / "review-1-quality.md").write_text("**Verdict: accepted**")
    (reviews_dir / "review-1-challenge.md").write_text("**Verdict: accepted**")
    (reviews_dir / "review-1-security.md").write_text("**Verdict: changes_requested**")

    stage_def = resolve_stage("review", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config=cfg) is True

    from forger.state import load_change

    state, _ = load_change(tmp_path / "change.md")
    assert state.pipeline.stage == "reviewed"


# --- Draft verify ---


def test_draft_verify_all_deliverables(tmp_path, config, base_state):
    base_state.pipeline.stage = "reviewed"
    _write_change(tmp_path, base_state)
    (tmp_path / "issue.md").write_text("# Bug fix\nDetails.")
    (tmp_path / "commit.txt").write_text("fix: resolve key error")
    (tmp_path / "changelog.txt").write_text("Fixed key error in graph handler.")
    (tmp_path / "pr.md").write_text("# Fix key error\nDetails.")

    stage_def = resolve_stage("draft", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is True

    from forger.state import load_change

    state, _ = load_change(tmp_path / "change.md")
    assert state.pipeline.stage == "drafted"


def test_draft_verify_missing_deliverable(tmp_path, config, base_state):
    base_state.pipeline.stage = "reviewed"
    _write_change(tmp_path, base_state)
    (tmp_path / "issue.md").write_text("# Bug fix")
    (tmp_path / "commit.txt").write_text("fix: resolve key error")
    # Missing changelog.txt and pr.md

    stage_def = resolve_stage("draft", "sentry")
    verify_fn = load_verify(stage_def)
    assert verify_fn(tmp_path, config) is False


# --- Diagnosis tests ---


class TestDiagnosisOnVerifyFailure:
    def test_missing_file_writes_diagnosis(self, tmp_path, config, base_state):
        base_state.pipeline.stage = "triaged"
        _write_change(tmp_path, base_state)

        stage_def = resolve_stage("analyze", "sentry")
        verify_fn = load_verify(stage_def)
        assert verify_fn(tmp_path, config) is False

        state, _ = load_change(tmp_path / "change.md")
        assert state.pipeline.diagnosis is not None
        assert "analysis.md not produced" in state.pipeline.diagnosis.what_failed
        assert "not produced" in state.pipeline.blocked_reason

    def test_evidence_exit_code_writes_diagnosis(self, tmp_path, config, base_state):
        base_state.pipeline.stage = "fix-chosen"
        base_state.evidence["fix_verified"] = EvidenceEntry(
            exit_code=1, last_run="2026-07-18", summary="AssertionError in test_foo"
        )
        base_state.evidence["lint"] = EvidenceEntry(exit_code=0, last_run="2026-07-18")
        _write_change(tmp_path, base_state)

        stage_def = resolve_stage("implement", "sentry")
        verify_fn = load_verify(stage_def)
        assert verify_fn(tmp_path, config) is False

        state, _ = load_change(tmp_path / "change.md")
        assert state.pipeline.diagnosis is not None
        assert "AssertionError in test_foo" in state.pipeline.diagnosis.what_failed

    def test_missing_evidence_shows_na(self, tmp_path, config, base_state):
        base_state.pipeline.stage = "fix-chosen"
        _write_change(tmp_path, base_state)

        stage_def = resolve_stage("implement", "sentry")
        verify_fn = load_verify(stage_def)
        assert verify_fn(tmp_path, config) is False

        state, _ = load_change(tmp_path / "change.md")
        assert state.pipeline.diagnosis is not None
        assert "N/A" in state.pipeline.blocked_reason

    def test_gate_unresolved_writes_diagnosis(self, tmp_path, config, base_state):
        base_state.pipeline.stage = "proven"
        base_state.gates["fix_choice"] = Gate(required=True, resolved=None)
        _write_change(tmp_path, base_state)
        (tmp_path / "fix-options.md").write_text("# Options")

        stage_def = resolve_stage("fix_options", "sentry")
        verify_fn = load_verify(stage_def)
        assert verify_fn(tmp_path, config) is False

        state, _ = load_change(tmp_path / "change.md")
        assert state.pipeline.diagnosis is not None
        assert "fix_choice" in state.pipeline.diagnosis.what_failed
        assert "gate" in state.pipeline.diagnosis.suggested_action.lower()

    def test_success_clears_diagnosis(self, tmp_path, config, base_state):
        base_state.pipeline.stage = "triaged"
        from forger.state import Diagnosis

        base_state.pipeline.diagnosis = Diagnosis(
            what_failed="old failure", suggested_action="old"
        )
        base_state.pipeline.blocked_reason = "old"
        _write_change(tmp_path, base_state)
        (tmp_path / "analysis.md").write_text("# Root cause\nFound it.")

        stage_def = resolve_stage("analyze", "sentry")
        verify_fn = load_verify(stage_def)
        assert verify_fn(tmp_path, config) is True

        state, _ = load_change(tmp_path / "change.md")
        assert state.pipeline.diagnosis is None
        assert state.pipeline.blocked_reason is None

    def test_evidence_summary_in_diagnosis(self, tmp_path, config, base_state):
        base_state.pipeline.stage = "fix-chosen"
        base_state.evidence["fix_verified"] = EvidenceEntry(
            exit_code=1, last_run="2026-07-18", summary="3 tests fail"
        )
        base_state.evidence["lint"] = EvidenceEntry(
            exit_code=0, last_run="2026-07-18", summary="clean"
        )
        _write_change(tmp_path, base_state)

        stage_def = resolve_stage("implement", "sentry")
        verify_fn = load_verify(stage_def)
        assert verify_fn(tmp_path, config) is False

        state, _ = load_change(tmp_path / "change.md")
        diag = state.pipeline.diagnosis
        assert diag is not None
        assert diag.evidence_summary["fix_verified"] == "3 tests fail"
        assert diag.evidence_summary["lint"] == "clean"
