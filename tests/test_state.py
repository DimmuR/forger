from forger.state import (
    TERMINAL_STAGES,
    ChangeState,
    Diagnosis,
    PipelineState,
    load_change,
    save_change,
)

FIXTURE_16K = """\
---
id: sentry-ACME-APP-16K
title: "KeyError: 13844628"
origin: sentry
created: "2026-07-10"
updated: "2026-07-18"
pipeline:
  stage: drafted
  flow: [analyze, prove, fix_options, implement, review, draft]
  parked_reason: null
gates:
  fix_choice:
    required: false
    resolved: a
    rationale: "auto: quick-win"
evidence:
  proof_test:
    path: "tests/test_bug.py::test_it"
    exit_code: 1
    last_run: "2026-07-18"
  fix_verified:
    exit_code: 0
    last_run: "2026-07-18"
  lint:
    exit_code: 0
    last_run: "2026-07-18"
github:
  issue: null
  branch: null
  pr: null
---

KeyError: 13844628 in graph handler when processing deleted nodes.
"""

FIXTURE_N3 = """\
---
id: sentry-ACME-APP-N3
title: "TypeError in batch processor"
origin: sentry
created: "2026-06-01"
updated: "2026-07-18"
pipeline:
  stage: pr-open
  flow: [analyze, prove, fix_options, implement, review, draft]
  parked_reason: null
gates:
  fix_choice:
    required: false
    resolved: b
    rationale: "structural fix needed"
evidence:
  proof_test:
    path: "tests/test_batch.py::test_type_error"
    exit_code: 1
    last_run: "2026-07-10"
  fix_verified:
    exit_code: 0
    last_run: "2026-07-18"
github:
  issue: null
  branch: null
  pr: "https://github.com/example-org/example-project/pull/9"
---

TypeError in batch processor when handling None values.
"""


def test_load_16k(tmp_path):
    change_path = tmp_path / "change.md"
    change_path.write_text(FIXTURE_16K)
    state, body = load_change(change_path)
    assert state.id == "sentry-ACME-APP-16K"
    assert state.title == "KeyError: 13844628"
    assert state.origin == "sentry"
    assert state.pipeline.stage == "drafted"
    assert state.gates["fix_choice"].resolved == "a"
    assert state.evidence["proof_test"].exit_code == 1
    assert state.evidence["fix_verified"].exit_code == 0
    assert state.github.issue is None
    assert "KeyError: 13844628" in body


def test_load_n3(tmp_path):
    change_path = tmp_path / "change.md"
    change_path.write_text(FIXTURE_N3)
    state, _body = load_change(change_path)
    assert state.id == "sentry-ACME-APP-N3"
    assert state.pipeline.stage == "pr-open"
    assert state.github.pr == "https://github.com/example-org/example-project/pull/9"


def test_round_trip(tmp_path):
    change_path = tmp_path / "change.md"
    change_path.write_text(FIXTURE_16K)
    state, body = load_change(change_path)
    out_path = tmp_path / "out-change.md"
    save_change(out_path, state, body)
    state2, body2 = load_change(out_path)
    assert state2.id == state.id
    assert state2.pipeline.stage == state.pipeline.stage
    assert state2.gates["fix_choice"].resolved == state.gates["fix_choice"].resolved
    assert (
        state2.evidence["proof_test"].exit_code
        == state.evidence["proof_test"].exit_code
    )
    assert "KeyError: 13844628" in body2


def test_minimal_change(tmp_path):
    minimal = tmp_path / "change.md"
    minimal.write_text("""---
id: test-001
title: "Test bug"
origin: manual
created: "2026-07-18"
updated: "2026-07-18"
pipeline:
  stage: analyze
---

A test bug description.
""")
    state, body = load_change(minimal)
    assert state.id == "test-001"
    assert state.pipeline.stage == "analyze"
    assert state.gates == {}
    assert "test bug" in body


def test_flow_field_ignored(tmp_path):
    """Legacy change.md files with flow field should load without error."""
    change = tmp_path / "change.md"
    change.write_text("""---
id: test-002
title: "Legacy bug"
origin: sentry
created: "2026-07-18"
updated: "2026-07-18"
pipeline:
  stage: triaged
  flow: [analyze, prove, implement, draft]
---

Old format with flow.
""")
    state, _body = load_change(change)
    assert state.id == "test-002"
    assert state.pipeline.stage == "triaged"
    # flow is silently ignored (extra="ignore")
    assert not hasattr(state.pipeline, "flow") or not getattr(
        state.pipeline, "flow", None
    )


def test_terminal_stages():
    assert "parked" in TERMINAL_STAGES
    assert "pr-open" in TERMINAL_STAGES


def test_legacy_fields_silently_ignored():
    """Legacy YAML with surface/category/flags at pipeline level loads without error."""
    state = ChangeState(
        id="test-002",
        title="Test",
        origin="sentry",
        created="2026-07-18",
        updated="2026-07-18",
        pipeline=PipelineState.model_validate(
            {
                "stage": "triaged",
                "surface": "backend",
                "category": "quick-win",
                "flags": ["regression"],
            }
        ),
    )
    assert state.pipeline.stage == "triaged"
    assert state.pipeline.source_properties == {}


def test_source_properties_round_trip(tmp_path):
    """source_properties survive save/load round-trip."""
    state = ChangeState(
        id="test-003",
        title="Test",
        origin="manual",
        created="2026-07-18",
        updated="2026-07-18",
        pipeline=PipelineState(
            stage="triaged",
            source_properties={"custom_key": "custom_value"},
        ),
    )
    path = tmp_path / "change.md"
    save_change(path, state, "body")
    content = path.read_text()
    assert "custom_key: custom_value" in content

    state2, _ = load_change(path)
    assert state2.pipeline.source_properties["custom_key"] == "custom_value"


def test_empty_source_properties_omitted(tmp_path):
    """Empty source_properties dict is not written to YAML."""
    state = ChangeState(
        id="test-003b",
        title="Test",
        origin="manual",
        created="2026-07-18",
        updated="2026-07-18",
        pipeline=PipelineState(stage="triaged"),
    )
    path = tmp_path / "change.md"
    save_change(path, state, "body")
    content = path.read_text()
    assert "source_properties" not in content


def test_origin_required():
    """origin has no default -- must be provided."""
    import pytest

    with pytest.raises(ValueError):
        ChangeState(
            id="test-004",
            title="Test",
            # no origin
            created="2026-07-18",
            updated="2026-07-18",
            pipeline=PipelineState(stage="triaged"),
        )


def test_diagnosis_round_trip(tmp_path):
    """Diagnosis survives save/load round-trip."""
    state = ChangeState(
        id="test-diag",
        title="Test",
        origin="sentry",
        created="2026-07-18",
        updated="2026-07-18",
        pipeline=PipelineState(
            stage="fix-chosen",
            blocked_reason="fix_verified: 3 tests fail",
            diagnosis=Diagnosis(
                what_failed="fix_verified: 3 tests fail",
                evidence_summary={"fix_verified": "3 tests fail", "lint": "clean"},
                suggested_action="Re-run from this stage",
            ),
        ),
    )
    path = tmp_path / "change.md"
    save_change(path, state, "body")
    state2, _ = load_change(path)
    assert state2.pipeline.diagnosis is not None
    assert state2.pipeline.diagnosis.what_failed == "fix_verified: 3 tests fail"
    assert state2.pipeline.diagnosis.evidence_summary["lint"] == "clean"
    assert state2.pipeline.blocked_reason == "fix_verified: 3 tests fail"


def test_diagnosis_none_omitted_from_yaml(tmp_path):
    """No diagnosis key in YAML when diagnosis is None."""
    state = ChangeState(
        id="test-no-diag",
        title="Test",
        origin="sentry",
        created="2026-07-18",
        updated="2026-07-18",
        pipeline=PipelineState(stage="triaged"),
    )
    path = tmp_path / "change.md"
    save_change(path, state, "body")
    content = path.read_text()
    assert "diagnosis" not in content
