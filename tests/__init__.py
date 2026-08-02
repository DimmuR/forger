"""Shared test helpers."""

from forger.state import ChangeState, PipelineState

_PIPELINE_FIELDS = set(PipelineState.model_fields)


def make_state(stage="triaged", **kwargs):
    """Factory for ChangeState with sensible defaults.

    Pipeline-level kwargs (stage, parked_reason, stack) are forwarded to
    PipelineState. Everything else goes to ChangeState (e.g. github=...).
    """
    pipeline_kwargs = {"stage": stage}
    state_kwargs = {}
    for k, v in kwargs.items():
        if k in _PIPELINE_FIELDS:
            pipeline_kwargs[k] = v
        else:
            state_kwargs[k] = v
    return ChangeState(
        id="sentry-TEST-001",
        title="Test bug",
        origin="sentry",
        created="2026-07-18",
        updated="2026-07-18",
        pipeline=PipelineState(**pipeline_kwargs),
        **state_kwargs,
    )
