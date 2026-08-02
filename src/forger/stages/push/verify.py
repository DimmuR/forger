"""Push stage: commit, push branch, create issue and PR. Harness-only (no LLM)."""

from pathlib import Path

from forger.config import ProjectConfig
from forger.git import (
    commit,
    create_issue,
    create_pr,
    current_branch,
    repo_root,
    switch_gh_account,
)
from forger.git import push as git_push
from forger.stages import check_stage_guards
from forger.state import save_change


def verify(run_dir: Path, config: ProjectConfig) -> bool:
    guards = check_stage_guards(run_dir, "drafted")
    if guards is None:
        return False
    state, body = guards
    change_path = run_dir / "change.md"

    work_dir = repo_root(run_dir)

    if config.gh_account:
        try:
            switch_gh_account(config.gh_account, work_dir)
        except RuntimeError as e:
            print(f"  ⛔ {e}", flush=True)

    # Commit
    commit_file = run_dir / "commit.txt"
    if commit_file.exists():
        try:
            sha = commit(commit_file, work_dir)
            if sha:
                print(f"  Committed: {sha}", flush=True)
            else:
                print("  Nothing to commit (already committed)", flush=True)
        except RuntimeError as e:
            state.pipeline.parked_reason = f"Push errors: commit: {e}"
            save_change(change_path, state, body)
            print(f"  ⛔ Commit failed: {e}", flush=True)
            return False

    # Push branch
    branch = current_branch(work_dir)
    if branch and branch != config.base_branch:
        try:
            git_push(branch, work_dir, branch_prefix=config.branch_prefix)
            print(f"  Pushed: {branch}", flush=True)
            state.github.branch = branch
        except RuntimeError as e:
            state.pipeline.parked_reason = f"Push errors: push: {e}"
            save_change(change_path, state, body)
            print(f"  ⛔ Push failed: {e}", flush=True)
            return False

    # Issue
    issue_file = run_dir / "issue.md"
    if issue_file.exists() and not state.github.issue:
        try:
            content = issue_file.read_text()
            lines = content.splitlines()
            title = lines[0].lstrip("# ").strip() if lines else "Untitled"
            url = create_issue(title, issue_file, cwd=work_dir)
            print(f"  Issue: {url}", flush=True)
            state.github.issue = url
        except RuntimeError as e:
            state.pipeline.parked_reason = f"Push errors: issue: {e}"
            save_change(change_path, state, body)
            print(f"  ⛔ Issue creation failed: {e}", flush=True)
            return False

    # PR
    pr_file = run_dir / "pr.md"
    if pr_file.exists() and not state.github.pr:
        try:
            content = pr_file.read_text()
            lines = content.splitlines()
            title = lines[0].lstrip("# ").strip() if lines else "Untitled"
            url = create_pr(title, pr_file, base=config.base_branch, cwd=work_dir)
            print(f"  PR: {url}", flush=True)
            state.github.pr = url
        except RuntimeError as e:
            state.pipeline.parked_reason = f"Push errors: pr: {e}"
            save_change(change_path, state, body)
            print(f"  ⛔ PR creation failed: {e}", flush=True)
            return False

    state.pipeline.stage = "pr-open"
    save_change(change_path, state, body)
    return True
