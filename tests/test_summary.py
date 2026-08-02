"""Tests for RunSummary data extraction."""

import pytest

from forger.orchestrator import RunOutcome
from forger.state import (
    EvidenceEntry,
    Gate,
    save_change,
)
from forger.summary import RunSummary
from tests import make_state


@pytest.fixture
def run_dir(tmp_path):
    return tmp_path


def _outcome(**kwargs):
    defaults = {"final_stage": "triaged", "stages_executed": 1}
    defaults.update(kwargs)
    return RunOutcome(**defaults)


class TestFromRun:
    def test_basic_extraction(self, run_dir):
        state = make_state(stage="analyzed")
        save_change(run_dir / "change.md", state, "Bug description.")
        summary = RunSummary.from_run(run_dir, _outcome(), "sentry", "TEST-001")
        assert summary is not None
        assert summary.title == "Test bug"
        assert summary.stage == "analyzed"
        assert summary.source == "sentry"
        assert summary.issue_id == "TEST-001"

    def test_missing_change_returns_none(self, run_dir):
        summary = RunSummary.from_run(run_dir, _outcome(), "sentry", "TEST-001")
        assert summary is None

    def test_parked_reason(self, run_dir):
        state = make_state(stage="analyzed", parked_reason="Cannot reproduce")
        save_change(run_dir / "change.md", state, "Body.")
        summary = RunSummary.from_run(run_dir, _outcome(), "sentry", "TEST-001")
        assert summary.parked_reason == "Cannot reproduce"
        assert summary.blocked_reason is None

    def test_blocked_reason_from_outcome(self, run_dir):
        state = make_state(stage="analyzed")
        save_change(run_dir / "change.md", state, "Body.")
        outcome = _outcome(blocked_reason="Runner failed")
        summary = RunSummary.from_run(run_dir, outcome, "sentry", "TEST-001")
        assert summary.blocked_reason == "Runner failed"

    def test_parked_suppresses_blocked(self, run_dir):
        state = make_state(stage="analyzed", parked_reason="Parked reason")
        save_change(run_dir / "change.md", state, "Body.")
        outcome = _outcome(blocked_reason="Runner failed too")
        summary = RunSummary.from_run(run_dir, outcome, "sentry", "TEST-001")
        assert summary.parked_reason == "Parked reason"
        assert summary.blocked_reason is None

    def test_evidence_extraction(self, run_dir):
        state = make_state(stage="proven")
        state.evidence["proof_test"] = EvidenceEntry(
            path="tests/test_it.py", exit_code=1, summary="Test fails"
        )
        save_change(run_dir / "change.md", state, "Body.")
        summary = RunSummary.from_run(run_dir, _outcome(), "sentry", "TEST-001")
        assert len(summary.evidence) == 1
        assert summary.evidence[0].key == "proof_test"
        assert summary.evidence[0].exit_code == 1
        assert summary.evidence[0].summary == "Test fails"

    def test_gate_extraction(self, run_dir):
        state = make_state(stage="proven")
        state.gates["fix_choice"] = Gate(required=True, resolved=None)
        state.gates["deploy_ok"] = Gate(
            required=False, resolved="yes", rationale="auto"
        )
        save_change(run_dir / "change.md", state, "Body.")
        summary = RunSummary.from_run(run_dir, _outcome(), "sentry", "TEST-001")
        assert len(summary.unresolved_gates) == 1
        assert summary.unresolved_gates[0].key == "fix_choice"
        assert len(summary.resolved_gates) == 1
        assert summary.resolved_gates[0].key == "deploy_ok"
        assert summary.resolved_gates[0].resolved == "yes"

    def test_artifacts_listed(self, run_dir):
        state = make_state(stage="analyzed")
        save_change(run_dir / "change.md", state, "Body.")
        (run_dir / "analysis.md").write_text("Root cause found.")
        (run_dir / "run.log").write_text("log content")
        (run_dir / ".hidden").write_text("hidden")
        summary = RunSummary.from_run(run_dir, _outcome(), "sentry", "TEST-001")
        assert "analysis.md" in summary.artifacts
        assert "change.md" in summary.artifacts
        assert "run.log" not in summary.artifacts
        assert ".hidden" not in summary.artifacts

    def test_fix_options_parsed(self, run_dir):
        state = make_state(stage="fix-chosen")
        save_change(run_dir / "change.md", state, "Body.")
        (run_dir / "fix-options.md").write_text(
            "## Option A: minimal fix\nDetails.\n\n"
            "## Option B: proper fix\nDetails.\n\n"
            "## Recommendation\nGo with A.\n"
        )
        summary = RunSummary.from_run(run_dir, _outcome(), "sentry", "TEST-001")
        assert "Option A: minimal fix" in summary.fix_options
        assert "Option B: proper fix" in summary.fix_options
        assert summary.fix_recommendation == "Go with A."

    def test_github_pr(self, run_dir):
        state = make_state(stage="pr-open")
        state.github.pr = "https://github.com/org/repo/pull/42"
        save_change(run_dir / "change.md", state, "Body.")
        summary = RunSummary.from_run(run_dir, _outcome(), "sentry", "TEST-001")
        assert summary.github_pr == "https://github.com/org/repo/pull/42"

    def test_body_lines_extraction(self, run_dir):
        state = make_state(stage="triaged")
        save_change(run_dir / "change.md", state, "Bug details here.\nMore info.")
        summary = RunSummary.from_run(run_dir, _outcome(), "sentry", "TEST-001")
        assert "Bug details here." in summary.body_lines
        assert "More info." in summary.body_lines
