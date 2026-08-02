"""change.md state models and read/write."""

__all__ = [
    "TERMINAL_STAGES",
    "ChangeState",
    "EvidenceEntry",
    "Gate",
    "GithubState",
    "PipelineState",
    "RunOutcome",
    "load_change",
    "save_change",
]

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter
from pydantic import BaseModel, field_validator


class PipelineState(BaseModel):
    stage: str
    stack: str | None = None
    source_properties: dict[str, Any] = {}
    parked_reason: str | None = None

    model_config = {"extra": "ignore"}

    def source_prop(self, key: str, default: Any = None) -> Any:
        """Typed accessor for source-specific properties."""
        return self.source_properties.get(key, default)


class Gate(BaseModel):
    required: bool = False
    resolved: str | None = None
    rationale: str | None = None


class EvidenceEntry(BaseModel):
    path: str | None = None
    exit_code: int | None = None
    last_run: str | None = None
    summary: str | None = None

    @field_validator("last_run", mode="before")
    @classmethod
    def _coerce_last_run(cls, v: Any) -> str | None:
        return _coerce_date(v)


class GithubState(BaseModel):
    issue: str | None = None
    branch: str | None = None
    pr: str | None = None


def _coerce_date(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return str(v)


class ChangeState(BaseModel):
    id: str
    title: str
    origin: str
    created: str = ""
    updated: str = ""

    @field_validator("created", "updated", mode="before")
    @classmethod
    def _coerce_dates(cls, v: Any) -> str:
        return _coerce_date(v) or ""

    pipeline: PipelineState
    gates: dict[str, Gate] = {}
    evidence: dict[str, EvidenceEntry] = {}
    github: GithubState = GithubState()

    @field_validator("evidence", mode="before")
    @classmethod
    def _clean_evidence(cls, v: Any) -> dict:
        if not isinstance(v, dict):
            return {}
        cleaned = {}
        for key, val in v.items():
            if val is None:
                continue
            if isinstance(val, dict):
                cleaned[key] = EvidenceEntry.model_validate(val)
            elif isinstance(val, EvidenceEntry):
                cleaned[key] = val
        return cleaned


TERMINAL_STAGES = {"parked", "pr-open"}


@dataclass
class RunOutcome:
    final_stage: str
    stages_executed: int
    blocked_reason: str | None = None
    final_run_dir: Path | None = None


def load_change(path: Path) -> tuple[ChangeState, str]:
    """Parse change.md into (ChangeState, markdown body)."""
    post = frontmatter.load(str(path))
    metadata = dict(post.metadata)
    state = ChangeState.model_validate(metadata)
    return state, post.content


def save_change(path: Path, state: ChangeState, body: str) -> None:
    """Write change.md with updated frontmatter + preserved body."""
    metadata = state.model_dump(mode="json", exclude_none=True)
    pipeline = metadata.get("pipeline")
    if isinstance(pipeline, dict) and not pipeline.get("source_properties"):
        pipeline.pop("source_properties", None)
    post = frontmatter.Post(body, **metadata)
    path.write_text(frontmatter.dumps(post) + "\n")
