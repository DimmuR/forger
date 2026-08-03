"""Stage registry and resolution logic."""

__all__ = [
    "StageDef",
    "check_stage_guards",
    "load_verify",
    "resolve_stage",
    "verify_stage",
]

import importlib
import importlib.util
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from forger.config import ProjectConfig
from forger.pipeline import STAGE_BY_NAME, VerifyCheck
from forger.state import (
    TERMINAL_STAGES,
    ChangeState,
    Diagnosis,
    load_change,
    save_change,
)


@dataclass
class StageDef:
    name: str
    path: Path
    prompt_path: Path | None
    references: list[Path] = field(default_factory=list)
    verify_module: str | None = None


def _package_stages_dir() -> Path:
    """Resolve the built-in stages directory from the installed package."""
    return Path(__file__).parent


def resolve_stage(
    stage_name: str, source: str, project_dir: Path | None = None
) -> StageDef:
    """Resolve stage definition with fallback: project source-specific → project generic → package source-specific → package generic."""
    candidates: list[Path] = []

    if project_dir:
        project_stages = project_dir / ".forger" / "stages"
        candidates.append(project_stages / f"{source}_{stage_name}")
        candidates.append(project_stages / stage_name)

    pkg_stages = _package_stages_dir()
    candidates.append(pkg_stages / f"{source}_{stage_name}")
    candidates.append(pkg_stages / stage_name)

    for candidate in candidates:
        prompt_path = candidate / "prompt.md"
        has_prompt = prompt_path.exists()
        has_verify = (candidate / "verify.py").exists()

        if candidate.exists() and (has_prompt or has_verify):
            references = []
            refs_dir = candidate / "references"
            if refs_dir.exists():
                references = sorted(refs_dir.glob("*.md"))

            verify_module = None
            if has_verify:
                verify_module = str(candidate / "verify.py")

            return StageDef(
                name=stage_name,
                path=candidate,
                prompt_path=prompt_path if has_prompt else None,
                references=references,
                verify_module=verify_module,
            )

    raise FileNotFoundError(
        f"No stage definition found for '{stage_name}' (source='{source}'). "
        f"Searched: {[str(c) for c in candidates]}"
    )


def _make_declarative_verify(
    check: VerifyCheck, pre_stage: str, post_stage: str
) -> Callable[[Path, "ProjectConfig"], bool]:
    """Build a verify function from a VerifyCheck spec."""

    def _check_fn(run_dir: Path, state: ChangeState) -> list[str]:
        reasons: list[str] = []
        for f in check.required_files:
            if not (run_dir / f).exists():
                reasons.append(f"{f} not produced")
        for key, expected_code in check.evidence_checks:
            entry = state.evidence.get(key)
            if not entry:
                reasons.append(f"{key}: N/A")
            elif entry.exit_code != expected_code:
                summary = entry.summary or f"exit {entry.exit_code}"
                reasons.append(f"{key}: {summary}")
        if check.gate_resolved:
            gate = state.gates.get(check.gate_resolved)
            if not gate or not gate.resolved:
                reasons.append(f"Gate '{check.gate_resolved}' awaiting resolution")
        return reasons

    def verify(run_dir: Path, config: ProjectConfig) -> bool:
        return verify_stage(run_dir, config, post_stage, pre_stage, _check_fn)

    return verify


def load_verify(stage_def: StageDef) -> Callable[[Path, "ProjectConfig"], bool] | None:
    """Load verify function: from verify.py if present, else from declarative spec."""
    if stage_def.verify_module:
        spec = importlib.util.spec_from_file_location(
            f"forger.stages.{stage_def.name}.verify", stage_def.verify_module
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn: Callable[[Path, ProjectConfig], bool] = module.verify
        return fn

    stage_spec = STAGE_BY_NAME.get(stage_def.name)
    if stage_spec and stage_spec.verify:
        return _make_declarative_verify(
            stage_spec.verify, stage_spec.pre_state, stage_spec.post_state
        )

    return None


def check_stage_guards(run_dir: Path, pre_stage: str) -> tuple[ChangeState, str] | None:
    """Check terminal/parked/pre-state guards. Returns (state, body) if ok, None if blocked."""
    change_path = run_dir / "change.md"
    state, body = load_change(change_path)

    if state.pipeline.stage in TERMINAL_STAGES or state.pipeline.parked_reason:
        return None

    if state.pipeline.stage != pre_stage:
        return None

    return state, body


def verify_stage(
    run_dir: Path,
    config: ProjectConfig,
    target_stage: str,
    pre_stage: str,
    check_fn: Callable[[Path, ChangeState], list[str]],
) -> bool:
    """Common verify pattern: load state, check terminal/parked, check pre-state, run check, set stage, save."""
    change_path = run_dir / "change.md"
    state, body = load_change(change_path)

    if state.pipeline.stage in TERMINAL_STAGES or state.pipeline.parked_reason:
        return False

    if state.pipeline.stage != pre_stage:
        return False

    if state.pipeline.stage == target_stage:
        return True

    reasons = check_fn(run_dir, state)
    if reasons:
        evidence_summary = {
            k: e.summary or f"exit {e.exit_code}"
            for k, e in state.evidence.items()
            if e.summary or e.exit_code is not None
        }
        state.pipeline.blocked_reason = "; ".join(reasons)
        state.pipeline.diagnosis = Diagnosis(
            what_failed=reasons[0],
            evidence_summary=evidence_summary,
            suggested_action=_suggest_action(reasons),
        )
        save_change(change_path, state, body)
        return False

    state.pipeline.stage = target_stage
    state.pipeline.blocked_reason = None
    state.pipeline.diagnosis = None
    save_change(change_path, state, body)
    return True


_ACTION_HINTS: dict[str, str] = {
    "not produced": "Re-run stage — LLM may not have written required file",
    "N/A": "Re-run stage — evidence was never recorded",
    "Gate": "Resolve gate in TUI or pass --gate flag",
}


def _suggest_action(reasons: list[str]) -> str:
    for reason in reasons:
        for hint_key, action in _ACTION_HINTS.items():
            if hint_key in reason:
                return action
    return "Re-run from this stage"
