"""Create-PR stage: create draft PR from pr.md. Harness-only (no LLM)."""

from pathlib import Path

from forger.config import ProjectConfig
from forger.git import create_pr, repo_root
from forger.stages import check_stage_guards
from forger.state import save_change

CHANGE_FILE = "change.md"
PR_FILE = "pr.md"


def verify(run_dir: Path, config: ProjectConfig) -> bool:
    guards = check_stage_guards(run_dir, "issue-created")
    if guards is None:
        return False
    state, body = guards
    change_path = run_dir / CHANGE_FILE

    if state.github.pr:
        state.pipeline.stage = "pr-open"
        save_change(change_path, state, body)
        return True

    pr_file = run_dir / PR_FILE
    if not pr_file.exists():
        state.pipeline.parked_reason = f"create_pr: {PR_FILE} not found"
        save_change(change_path, state, body)
        print(f"  ⛔ {PR_FILE} not found", flush=True)
        return False

    work_dir = repo_root(run_dir)

    if state.github.issue:
        issue_number = state.github.issue.rstrip("/").rsplit("/", 1)[-1]
        pr_content = pr_file.read_text()
        updated = pr_content.replace("#<issue-number>", f"#{issue_number}")
        if updated != pr_content:
            pr_file.write_text(updated)

    try:
        content = pr_file.read_text()
        lines = content.splitlines()
        title = lines[0].lstrip("# ").strip() if lines else "Untitled"
        url = create_pr(title, pr_file, base=config.base_branch, cwd=work_dir)
        print(f"  PR: {url}", flush=True)
        state.github.pr = url
    except RuntimeError as e:
        state.pipeline.parked_reason = f"create_pr: {e}"
        save_change(change_path, state, body)
        print(f"  ⛔ PR creation failed: {e}", flush=True)
        return False

    state.pipeline.stage = "pr-open"
    save_change(change_path, state, body)
    return True
