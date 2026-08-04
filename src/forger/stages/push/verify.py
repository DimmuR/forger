"""Push stage: commit and push branch. Harness-only (no LLM)."""

from pathlib import Path

from forger.config import ProjectConfig
from forger.git import (
    commit,
    current_branch,
    repo_root,
    switch_gh_account,
)
from forger.git import push as git_push
from forger.stages import check_stage_guards
from forger.state import save_change

CHANGE_FILE = "change.md"
COMMIT_FILE = "commit.txt"


def verify(run_dir: Path, config: ProjectConfig) -> bool:
    guards = check_stage_guards(run_dir, "drafted")
    if guards is None:
        return False
    state, body = guards
    change_path = run_dir / CHANGE_FILE

    work_dir = repo_root(run_dir)

    if config.gh_account:
        try:
            switch_gh_account(config.gh_account, work_dir)
        except RuntimeError as e:
            print(f"  ⛔ {e}", flush=True)

    commit_file = run_dir / COMMIT_FILE
    if commit_file.exists():
        try:
            sha = commit(commit_file, work_dir)
            if sha:
                print(f"  Committed: {sha}", flush=True)
            else:
                print("  Nothing to commit (already committed)", flush=True)
        except RuntimeError as e:
            state.pipeline.parked_reason = f"push: commit: {e}"
            save_change(change_path, state, body)
            print(f"  ⛔ Commit failed: {e}", flush=True)
            return False

    branch = current_branch(work_dir)
    if branch and branch != config.base_branch:
        try:
            git_push(branch, work_dir, branch_prefix=config.branch_prefix)
            print(f"  Pushed: {branch}", flush=True)
            state.github.branch = branch
        except RuntimeError as e:
            state.pipeline.parked_reason = f"push: {e}"
            save_change(change_path, state, body)
            print(f"  ⛔ Push failed: {e}", flush=True)
            return False

    state.pipeline.stage = "pushed"
    save_change(change_path, state, body)
    return True
