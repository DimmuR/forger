"""Pipeline orchestration loop."""

__all__ = [
    "ensure_run_dir",
    "find_run_dir",
    "reset_to_stage",
    "run_pipeline",
]

import shutil
import time
from dataclasses import dataclass, replace
from pathlib import Path

from forger import worktree
from forger.config import ProjectConfig
from forger.pipeline import artifacts_for, next_stage, post_state_for, pre_state_for
from forger.prompt import render_prompt
from forger.runner import invoke_runner, resolve_model, resolve_runner, resolve_tools
from forger.stages import StageDef, load_verify, resolve_stage
from forger.state import (
    TERMINAL_STAGES,
    ChangeState,
    PipelineState,
    RunOutcome,
    load_change,
    save_change,
)

MAX_STAGES = 15

# Stages that modify code and require a worktree
CODE_STAGES = {"prove", "fix_options", "implement", "review", "draft"}


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

        self.run_dir = ensure_run_dir(source, issue_id, project_dir)
        self.canonical_run_dir = self.run_dir
        self.work_dir = repo_dir
        self.stages_executed = 0
        self.total_tokens = 0
        self.pipeline_start = time.monotonic()

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

    def run(self) -> RunOutcome:
        """Main orchestration loop. Runs stages until blocked or terminal."""
        self._setup_worktree()
        self._apply_gate_resolutions()

        try:
            for _ in range(MAX_STAGES):
                result = self._resolve_and_dispatch()
                if result is not None:
                    return result

            # Max stages reached
            state, _ = load_change(self.run_dir / "change.md")
            return self._outcome(
                final_stage=state.pipeline.stage,
                stages_executed=self.stages_executed,
                blocked_reason="Max stage transitions reached",
            )
        finally:
            self._cleanup_worktree()

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
            self.run_dir = self.canonical_run_dir
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
            log_file=log_file,
        )
        elapsed = int(time.monotonic() - start)

        if result.timed_out:
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
            print(
                f"{self._elapsed_str()} [{display_name}] runner exited {result.exit_code} ({elapsed}s)",
                flush=True,
            )
            return _StageResult(
                tokens=result.tokens,
                elapsed=elapsed,
                failed=True,
                blocked_reason=f"Runner failed at stage '{display_name}' (exit {result.exit_code})",
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

        model = resolve_model(stage_name, self.config)
        runner = resolve_runner(self.config)
        allowed_tools = resolve_tools(stage_name, self.config)
        return self._invoke_stage(
            stage_name, stage_def, state, model, runner, allowed_tools
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

            model = reviewer.model or resolve_model("review", self.config)
            runner = self.config.runners[reviewer.runner or self.config.default_runner]
            allowed_tools = resolve_tools("review", self.config)

            result = self._invoke_stage(
                "review",
                stage_def,
                state,
                model,
                runner,
                allowed_tools,
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
        print(f"{self._elapsed_str()} [{stage_name}] skipped", flush=True)
        post = post_state_for(stage_name)
        if post and change_path.exists():
            state, body = load_change(change_path)
            state.pipeline.stage = post
            save_change(change_path, state, body)
        self.stages_executed += 1
        return True

    def _maybe_create_worktree(self, stage_name: str) -> None:
        """Create worktree before code-modifying stages if needed."""
        if not (
            self.config.worktree
            and self.work_dir == self.repo_dir
            and stage_name in CODE_STAGES
        ):
            return
        self.work_dir = worktree.create(
            self.issue_id,
            self.repo_dir,
            self.config.base_branch,
            self.config.branch_prefix,
        )
        self.run_dir = worktree.relocate_run_dir(self.canonical_run_dir, self.work_dir)
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
            reason = f"Stage '{stage_name}' did not advance"
            final_stage = "unknown"
            if change_path.exists():
                state, _ = load_change(change_path)
                final_stage = state.pipeline.stage
                if state.pipeline.parked_reason:
                    reason = f"Parked: {state.pipeline.parked_reason}"
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

    def _resolve_and_dispatch(self) -> RunOutcome | None:
        """Handle one iteration of the main loop.

        Returns a RunOutcome if the pipeline should stop, or None to continue.
        """
        change_path = self.run_dir / "change.md"

        # Determine which stage to run next
        if not change_path.exists():
            stage_name: str | None = f"{self.source}_intake"
            state: ChangeState | None = None
        else:
            state, _ = load_change(change_path)
            if state.pipeline.stage in TERMINAL_STAGES or state.pipeline.parked_reason:
                stage_name = None
            else:
                stage_name = next_stage(state.pipeline.stage)

        if stage_name is None:
            blocked = None
            if state and state.pipeline.parked_reason:
                blocked = f"Parked: {state.pipeline.parked_reason}"
            return self._outcome(
                final_stage=state.pipeline.stage if state else "none",
                stages_executed=self.stages_executed,
                blocked_reason=blocked,
            )

        if self._maybe_skip(stage_name, change_path):
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
                pipeline=PipelineState(stage="intake"),
            )

        self._maybe_create_worktree(stage_name)

        stage_result = self._dispatch_stage(stage_name, stage_def, state)
        self.total_tokens += stage_result.tokens

        if stage_result.failed:
            return self._outcome(
                final_stage=state.pipeline.stage,
                stages_executed=self.stages_executed,
                blocked_reason=stage_result.blocked_reason,
            )

        return self._verify_and_report(stage_name, stage_def, stage_result)


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
