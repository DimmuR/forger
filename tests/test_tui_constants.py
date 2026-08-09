"""Tests for TUI constants — dynamic stage derivation."""

from forger.pipeline import STAGE_BY_NAME
from forger.tui.artifacts import STAGE_COLORS
from forger.tui.constants import STAGE_SHORT, stage_label


def test_stage_short_covers_all_stages():
    for name in STAGE_BY_NAME:
        assert name in STAGE_SHORT, f"STAGE_SHORT missing '{name}'"


def test_stage_short_overrides():
    assert STAGE_SHORT["sentry_intake"] == "intake"
    assert STAGE_SHORT["implement"] == "impl"
    assert STAGE_SHORT["create_issue"] == "issue"
    assert STAGE_SHORT["create_pr"] == "pr"
    assert STAGE_SHORT["create_patch"] == "patch"


def test_stage_short_defaults_to_name():
    assert STAGE_SHORT["analyze"] == "analyze"
    assert STAGE_SHORT["review"] == "review"


def test_stage_colors_covers_all_stages():
    for name in STAGE_BY_NAME:
        assert name in STAGE_COLORS, f"STAGE_COLORS missing '{name}'"


def test_stage_label_post_states():
    assert stage_label("analyzed") == "analyze"
    assert stage_label("pushed") == "push"
    assert stage_label("issue-created") == "issue"
    assert stage_label("pr-open") == "pr"
    assert stage_label("patched") == "patch"


def test_stage_label_unknown():
    assert stage_label("some-weird-state") == "some-weird-state"
