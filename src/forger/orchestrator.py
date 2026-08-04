"""Pipeline orchestration loop."""

__all__ = [
    "ensure_run_dir",
    "find_run_dir",
    "reset_to_stage",
    "run_pipeline",
]

import os
import shutil
import time
from dataclasses import dataclass, replace
from pathlib import Path

from forger import worktree
from forger.config import PipelineConfig, ProjectConfig
from forger.events import EventEmitter
from forger.pipeline import (
    StageSpec,
    artifacts_for,
    post_state_for,
    pre_state_for,
    resolve_pipeline_stages,
)
from forger.prompt import render_prompt
from forger.runner import (
    invoke_runner,
    resolve_effort,
    resolve_model,
    resolve_runner,
    resolve_timeout,
    resolve_tools,
)
from forger.stages import StageDef, load_verify, resolve_stage
from forger.state import (
    ChangeState,
    Diagnosis,
    PipelineState,
    RunOutcome,
    load_change,
    save_change,
)

MAX_STAGES = 15


@dataclass
class _StageResult:
    """Result of dispatching a single stage to the runner(s)."""

    tokens: int
    elapsed: int
    failed: bool = False
    blocked_reason: str | None = None


def find_run_dir(run_id: str, project_dir: Path) -> Path | None:
    """Scan all source dirs for a run matching this ID."""
    artifacts_dir = project_dir / ".forger" / "artifacts"
    if not artifacts_dir.exists():
        return None
    for source_dir in artifacts_dir.iterdir():
        if not source_dir.is_dir() or source_dir.name == "archive":
            continue
        candidate = source_dir / f"run-{run_id}"
        if candidate.exists() and (candidate / "change.md").exists():
            return candidate
        # Also try without run- prefix
        candidate = source_dir / run_id
        if candidate.exists() and (candidate / "change.md").exists():
            return candidate
    return None


def ensure_run_dir(source: str, issue_id: str, project_dir: Path) -> Path:
    """Create or find run directory."""
    run_id = f"run-{issue_id}"
    artifacts_dir = project_dir / ".forger" / "artifacts" / source
    run_dir = artifacts_dir / run_id

    if not run_dir.exists():
        run_dir.mkdir(parents=True)

    return run_dir


def reset_to_stage(run_dir: Path, from_stage: str) -> str:
    """Reset pipeline state so it reruns from *from_stage*.

    Sets state to the pre-state for *from_stage*, clears parked_reason,
    and deletes stage artifacts. Returns the new stage label for logging.
    """
    state, body = load_change(run_dir / "change.md")
    state.pipeline.stage = pre_state_for(from_stage) or from_stage
    state.pipeline.parked_reason = None
    save_change(run_dir / "change.md", state, body)

    for artifact in artifacts_for(from_stage):
        path = run_dir / artifact
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    return state.pipeline.stage


class PipelineRunner:
    """Encapsulates the state and logic for a single pipeline run."""

    def __init__(
        self,
        source: str,
        issue_id: str,
        config: ProjectConfig,
        project_dir: Path,
        repo_dir: Path,
        gate_resolutions: dict[str, str] | None = None,
        until_stage: str | None = None,
        skip_stages: set[str] | None = None,
    ):
        self.source = source
        self.issue_id = issue_id
        self.config = config
        self.project_dir = project_dir
        self.repo_dir = repo_dir
        self.gate_resolutions = gate_resolutions
        self.until_stage = until_stage
        self.skip_stages = skip_stages

        self.pipeline_config: PipelineConfig | None = config.pipelines.get(source)
        self.stage_specs: list[StageSpec] = self._resolve_stages()

        self.run_dir = ensure_run_dir(source, issue_id, project_dir)
        self.canonical_run_dir = self.run_dir
        self.work_dir = repo_dir
        self.stages_executed = 0
        self.total_tokens = 0
        self.pipeline_start = time.monotonic()
        self.events = EventEmitter(self.run_dir)
        self._lock_fd: int | None = None
        self._stage_cursor = 0

    def _resolve_stages(self) -> list[StageSpec]:
        if self.pipeline_config:
            return resolve_pipeline_stages(self.pipeline_config.stages)
        from forger.pipeline import STAGES

        return list(STAGES)

    def _outcome(
        self,
        final_stage: str,
        stages_executed: int,
        blocked_reason: str | None = None,
    ) -> RunOutcome:
        return RunOutcome(
            final_stage=final_stage,
            stages_executed=stages_executed,
            blocked_reason=blocked_reason,
            final_run_dir=self.canonical_run_dir,
        )

    def _acquire_lock(self) -> None:
        """Acquire exclusive fcntl lock for this run."""
        import contextlib

        from forger.tui.discovery import acquire_lock

        with contextlib.suppress(OSError):
            self._lock_fd = acquire_lock(self.issue_id, self.project_dir)

    def _release_lock(self) -> None:
        """Release the run lock if held."""
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    def run(self) -> RunOutcome:
        """Main orchestration loop. Runs stages until blocked or terminal."""
        self._acquire_lock()
        self.events.emit(
            "pipeline_start",
            source=self.source,
            issue_id=self.issue_id,
        )
        self._setup_worktree()
        self._apply_gate_resolutions()

        try:
            for _ in range(MAX_STAGES):
                result = self._resolve_and_dispatch()
                if result is not None:
                    self._emit_pipeline_end(result)
                    return result

            # Max stages reached
            state, _ = load_change(self.run_dir / "change.md")
            self._write_failure_diagnosis("pipeline", "Max stage transitions reached")
            outcome = self._outcome(
                final_stage=state.pipeline.stage,
                stages_executed=self.stages_executed,
                blocked_reason="Max stage transitions reached",
            )
            self._emit_pipeline_end(outcome)
            return outcome
        finally:
            self._cleanup_worktree()
            self.events.close()
            self._release_lock()

    def _emit_pipeline_end(self, outcome: RunOutcome) -> None:
        elapsed = time.monotonic() - self.pipeline_start
        self.events.emit(
            "pipeline_end",
            final_stage=outcome.final_stage,
            total_tokens=self.total_tokens,
            total_elapsed_seconds=int(elapsed),
            blocked_reason=outcome.blocked_reason,
        )

    def _elapsed_str(self) -> str:
        s = int(time.monotonic() - self.pipeline_start)
        return f"[{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}]"

    def _tokens_str(self, tokens: int) -> str:
        if tokens >= 1_000_000:
            return f"{tokens / 1_000_000:.1f}M"
        if tokens >= 1_000:
            return f"{tokens / 1_000:.1f}k"
        return str(tokens)

    def _cleanup_worktree(self) -> None:
        if self.config.worktree and self.work_dir != self.repo_dir:
            worktree.recover_artifacts(self.work_dir, self.canonical_run_dir)
            worktree.remove(self.issue_id, self.repo_dir, self.config.branch_prefix)
            self.events.emit("worktree", action="remove", path=str(self.work_dir))
            self.run_dir = self.canonical_run_dir
            self.events.reattach(self.run_dir)
            print(
                f"{self._elapsed_str()} Removed worktree: {self.work_dir}", flush=True
            )

    def _setup_worktree(self) -> None:
        """Attach to existing worktree if present."""
        if self.config.worktree:
            wt_path = worktree.path_for(self.issue_id, self.repo_dir)
            if wt_path:
                self.work_dir = wt_path
                self.run_dir = worktree.worktree_run_dir(wt_path)
                self.events.reattach(self.run_dir)
                self.events.emit("worktree", action="create", path=str(wt_path))
                print(f"[0:00:00] Using existing worktree: {wt_path}", flush=True)

    def _apply_gate_resolutions(self) -> None:
        """Write gate resolutions to change.md if provided."""
        if self.gate_resolutions and (self.run_dir / "change.md").exists():
            state, body = load_change(self.run_dir / "change.md")
            for key, value in self.gate_resolutions.items():
                if key in state.gates:
                    state.gates[key].resolved = value
            save_change(self.run_dir / "change.md", state, body)

    def _invoke_stage(
        self,
        stage_name: str,
        stage_def: StageDef,
        state: ChangeState,
        model: str,
        runner_template,
        allowed_tools: list[str] | None,
        effort: str | None = None,
        timeout: int | None = None,
        prompt_path: Path | None = None,
        log_name: str | None = None,
        token_offset: int = 0,
    ) -> _StageResult:
        """Shared dispatch: render prompt, invoke runner, check result."""
        display_name = log_name or stage_name
        actual_stage_def = stage_def
        if prompt_path and prompt_path != stage_def.prompt_path:
            actual_stage_def = replace(stage_def, prompt_path=prompt_path)

        prompt = render_prompt(
            actual_stage_def,
            state,
            self.config,
            self.run_dir,
            self.work_dir,
            self.project_dir,
        )
        log_file = self.run_dir / "run.log"

        combined_tokens = self.total_tokens + token_offset
        token_prefix = (
            f" {self._tokens_str(combined_tokens)}" if combined_tokens else ""
        )
        self.events.emit("stage_start", name=display_name, model=model)
        print(
            f"{self._elapsed_str()}{token_prefix} [{display_name}] started (model={model})",
            flush=True,
        )
        start = time.monotonic()

        result = invoke_runner(
            runner_template,
            prompt,
            self.work_dir,
            model,
            allowed_tools=allowed_tools,
            effort=effort,
            timeout=timeout,
            log_file=log_file,
            event_emitter=self.events,
        )
        elapsed = int(time.monotonic() - start)

        if result.timed_out:
            self.events.emit(
                "stage_end",
                name=display_name,
                tokens=result.tokens,
                elapsed_seconds=elapsed,
                success=False,
                error=f"Runner timed out at stage '{display_name}'",
            )
            print(
                f"{self._elapsed_str()} [{display_name}] timed out after {elapsed}s",
                flush=True,
            )
            return _StageResult(
                tokens=result.tokens,
                elapsed=elapsed,
                failed=True,
                blocked_reason=f"Runner timed out at stage '{display_name}'",
            )

        if result.exit_code != 0:
            error_msg = (
                f"Runner failed at stage '{display_name}' (exit {result.exit_code})"
            )
            self.events.emit(
                "stage_end",
                name=display_name,
                tokens=result.tokens,
                elapsed_seconds=elapsed,
                success=False,
                error=error_msg,
            )
            print(
                f"{self._elapsed_str()} [{display_name}] runner exited {result.exit_code} ({elapsed}s)",
                flush=True,
            )
            return _StageResult(
                tokens=result.tokens,
                elapsed=elapsed,
                failed=True,
                blocked_reason=error_msg,
            )

        self.events.emit(
            "stage_end",
            name=display_name,
            tokens=result.tokens,
            elapsed_seconds=elapsed,
            success=True,
            error=None,
        )
        return _StageResult(tokens=result.tokens, elapsed=elapsed)

    def _dispatch_stage(
        self,
        stage_name: str,
        stage_def: StageDef,
        state: ChangeState,
    ) -> _StageResult:
        """Invoke runner(s) for a stage. Handles multi-reviewer dispatch for review."""
        if stage_def.prompt_path is None:
            print(f"{self._elapsed_str()} [{stage_name}] harness stage", flush=True)
            return _StageResult(tokens=0, elapsed=0)

        if stage_name == "review":
            return self._dispatch_review(stage_def, state)

        pc = self.pipeline_config
        model = resolve_model(stage_name, self.config, pc)
        runner = resolve_runner(self.config)
        allowed_tools = resolve_tools(stage_name, self.config, pc)
        effort = resolve_effort(stage_name, self.config, pc)
        timeout = resolve_timeout(stage_name, self.config, pc)
        return self._invoke_stage(
            stage_name,
            stage_def,
            state,
            model,
            runner,
            allowed_tools,
            effort=effort,
            timeout=timeout,
        )

    def _dispatch_review(
        self,
        stage_def: StageDef,
        state: ChangeState,
    ) -> _StageResult:
        """Invoke runner for each reviewer in the review stage."""
        stage_tokens = 0
        review_start = time.monotonic()

        for reviewer in self.config.review.reviewers:
            role_file = stage_def.path / f"{reviewer.role}.md"
            role_prompt_path = (
                role_file if role_file.exists() else stage_def.prompt_path
            )

            pc = self.pipeline_config
            model = reviewer.model or resolve_model("review", self.config, pc)
            runner = self.config.runners[reviewer.runner or self.config.default_runner]
            allowed_tools = resolve_tools("review", self.config, pc)
            effort = resolve_effort("review", self.config, pc)
            timeout = resolve_timeout("review", self.config, pc)

            result = self._invoke_stage(
                "review",
                stage_def,
                state,
                model,
                runner,
                allowed_tools,
                effort=effort,
                timeout=timeout,
                prompt_path=role_prompt_path,
                log_name=f"review/{reviewer.role}",
                token_offset=stage_tokens,
            )
            stage_tokens += result.tokens

            if result.failed:
                return _StageResult(
                    tokens=stage_tokens,
                    elapsed=int(time.monotonic() - review_start),
                    failed=True,
                    blocked_reason=result.blocked_reason,
                )

        return _StageResult(
            tokens=stage_tokens, elapsed=int(time.monotonic() - review_start)
        )

    def _maybe_skip(self, stage_name: str, change_path: Path) -> bool:
        """Handle --skip flag. Returns True if stage was skipped."""
        if not (self.skip_stages and stage_name in self.skip_stages):
            return False
        self.events.emit("skip", name=stage_name)
        print(f"{self._elapsed_str()} [{stage_name}] skipped", flush=True)
        post = post_state_for(stage_name)
        if post and change_path.exists():
            state, body = load_change(change_path)
            state.pipeline.stage = post
            save_change(change_path, state, body)
        self.stages_executed += 1
        return True

    def _maybe_create_worktree(self, spec: StageSpec) -> None:
        """Create worktree before code-modifying stages if needed."""
        if not (
            self.config.worktree
            and self.work_dir == self.repo_dir
            and spec.needs_worktree
        ):
            return
        self.work_dir = worktree.create(
            self.issue_id,
            self.repo_dir,
            self.config.base_branch,
            self.config.branch_prefix,
        )
        self.run_dir = worktree.relocate_run_dir(self.canonical_run_dir, self.work_dir)
        self.events.reattach(self.run_dir)
        self.events.emit("worktree", action="create", path=str(self.work_dir))
        print(f"{self._elapsed_str()} Created worktree: {self.work_dir}", flush=True)

    def _verify_and_report(
        self, stage_name: str, stage_def: StageDef, stage_result: _StageResult
    ) -> RunOutcome | None:
        """Run verify, log result. Returns RunOutcome if blocked, None to continue."""
        change_path = self.run_dir / "change.md"
        verify_fn = load_verify(stage_def)
        advanced = verify_fn(self.run_dir, self.config) if verify_fn else True

        self.stages_executed += 1

        if not advanced:
            final_stage = "unknown"
            gate = None
            reason = f"Stage '{stage_name}' did not advance"
            if change_path.exists():
                state, _ = load_change(change_path)
                final_stage = state.pipeline.stage
                if state.pipeline.parked_reason:
                    reason = f"Parked: {state.pipeline.parked_reason}"
                elif state.pipeline.blocked_reason:
                    reason = state.pipeline.blocked_reason
                for gname, gval in state.gates.items():
                    if gval.required and gval.resolved is None:
                        gate = gname
                        break
            self.events.emit("blocked", reason=reason, gate=gate)
            print(
                f"{self._elapsed_str()} [{stage_name}] blocked — {reason}", flush=True
            )
            return self._outcome(
                final_stage=final_stage,
                stages_executed=self.stages_executed,
                blocked_reason=reason,
            )

        state, _ = load_change(change_path)
        token_suffix = (
            f" / +{self._tokens_str(stage_result.tokens)}"
            if stage_result.tokens
            else ""
        )
        print(
            f"{self._elapsed_str()} {self._tokens_str(self.total_tokens)} [{stage_name}] ✓ → {state.pipeline.stage} (+{stage_result.elapsed}s{token_suffix})",
            flush=True,
        )

        if self.until_stage and stage_name == self.until_stage:
            return self._outcome(
                final_stage=state.pipeline.stage,
                stages_executed=self.stages_executed,
            )

        return None

    def _write_failure_diagnosis(self, stage_name: str, what_failed: str) -> None:
        """Persist a Diagnosis to change.md for runner/timeout/max-stages failures."""
        change_path = self.run_dir / "change.md"
        if not change_path.exists():
            return
        state, body = load_change(change_path)
        evidence_summary = {
            k: e.summary or f"exit {e.exit_code}"
            for k, e in state.evidence.items()
            if e.summary or e.exit_code is not None
        }
        suggested = "Re-run from this stage"
        if "timed out" in what_failed.lower():
            suggested = f"Re-run {stage_name} (may need longer timeout)"
        elif "exit" in what_failed.lower():
            suggested = f"Check run.log for {stage_name} output, then re-run"
        state.pipeline.blocked_reason = what_failed
        state.pipeline.diagnosis = Diagnosis(
            what_failed=what_failed,
            evidence_summary=evidence_summary,
            suggested_action=suggested,
        )
        save_change(change_path, state, body)

    def _resolve_and_dispatch(self) -> RunOutcome | None:
        """Handle one iteration of the main loop.

        Returns a RunOutcome if the pipeline should stop, or None to continue.
        """
        change_path = self.run_dir / "change.md"

        # First call: no change.md yet — first stage in list is intake
        spec: StageSpec | None
        if not change_path.exists():
            spec = self.stage_specs[0]
            state: ChangeState | None = None
        else:
            state, _ = load_change(change_path)
            if state.pipeline.parked_reason:
                blocked = f"Parked: {state.pipeline.parked_reason}"
                self.events.emit("blocked", reason=blocked, gate=None)
                return self._outcome(
                    final_stage=state.pipeline.stage,
                    stages_executed=self.stages_executed,
                    blocked_reason=blocked,
                )
            spec = self._next_spec(state.pipeline.stage)

        if spec is None:
            return self._outcome(
                final_stage=state.pipeline.stage if state else "none",
                stages_executed=self.stages_executed,
            )

        stage_name = spec.name

        if self._maybe_skip(stage_name, change_path):
            self._stage_cursor += 1
            return None

        try:
            stage_def = resolve_stage(stage_name, self.source, self.project_dir)
        except FileNotFoundError as e:
            return self._outcome(
                final_stage=state.pipeline.stage if state else "none",
                stages_executed=self.stages_executed,
                blocked_reason=str(e),
            )

        if state is None:
            state = ChangeState(
                id=f"{self.source}-{self.issue_id}",
                title=self.issue_id,
                origin=self.source,
                created=time.strftime("%Y-%m-%d"),
                updated=time.strftime("%Y-%m-%d"),
                pipeline=PipelineState(stage=spec.pre_state),
            )

        self._maybe_create_worktree(spec)

        stage_result = self._dispatch_stage(stage_name, stage_def, state)
        self.total_tokens += stage_result.tokens

        if stage_result.failed:
            self._write_failure_diagnosis(
                stage_name, stage_result.blocked_reason or "Runner failed"
            )
            return self._outcome(
                final_stage=state.pipeline.stage,
                stages_executed=self.stages_executed,
                blocked_reason=stage_result.blocked_reason,
            )

        self._stage_cursor += 1
        return self._verify_and_report(stage_name, stage_def, stage_result)

    def _next_spec(self, current_stage: str) -> StageSpec | None:
        """Find next stage to run based on current pipeline state."""
        for i, spec in enumerate(self.stage_specs):
            if spec.pre_state == current_stage:
                self._stage_cursor = i
                return spec
        return None


def run_pipeline(
    source: str,
    issue_id: str,
    config: ProjectConfig,
    project_dir: Path,
    repo_dir: Path,
    gate_resolutions: dict[str, str] | None = None,
    until_stage: str | None = None,
    skip_stages: set[str] | None = None,
) -> RunOutcome:
    """Main orchestration loop. Runs stages until blocked or terminal."""
    runner = PipelineRunner(
        source=source,
        issue_id=issue_id,
        config=config,
        project_dir=project_dir,
        repo_dir=repo_dir,
        gate_resolutions=gate_resolutions,
        until_stage=until_stage,
        skip_stages=skip_stages,
    )
    return runner.run()
